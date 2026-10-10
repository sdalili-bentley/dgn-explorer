"""DGN Explorer: reversible DGN V8 compound-storage extraction and rebuilding.

Install: see README.md and review DEPENDENCY_POLICY.md first.
Extract: dgn-explorer unpack input.dgn unpacked
Rebuild: dgn-explorer pack unpacked edited.dgn

Edit text-element/node JSON under objects/, field metadata JSON under fields/,
XML/JSON/text under content/ and
structured JSON under data/ and framing/. objects/index.ro.json is a read-only
discovery index; edit the referenced files, not the index. Text/font/origin/
orientation/size fields are exposed, but glyph extents, ranges, rich-text
metadata and parent layouts require validation in the DGN application.
field-choices.ro.json lists all 15 placeholder link choices. Existing compatible
Link Name fields support placeholder_link_type changes; these do not assign
a real target, change Field Type, or resolve the app's placeholder-field error.
Document properties, attributes, element chunk headers and framing have
reversible representations. Known lengths,
attribute counts and property offsets are recalculated on rebuild. Opaque
payloads use reversible escaped byte strings (or --bytes-mode hex), not guessed schemas. Legacy binary extraction
folders still work. Re-extract to obtain the new readable representations.

Open WRITABLE.ro.md for links to every editable .rw file. .ro files are
read-only; .rw files list supported edits under editing and still contain restricted fields and immutable IDs.
Keep manifest.rw.json and original.dgn. The latter preserves storage metadata
and exact unchanged compressed bytes. Add/delete streams via the manifest.
This is not a full geometry/object serializer: unsupported application data,
IDs, cross-stream indexes and signatures are not repaired automatically. V7
and password-protected DGN are unsupported. Rebuilding requires Windows.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tempfile
from typing import Any, cast
from urllib.parse import quote
import uuid
import xml.etree.ElementTree as ET
import zlib


FORMAT = "dgn-folder-v2"
CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
DEFAULT_LIMIT = 512 * 1024 * 1024
EDITOR_LIMIT = 64 * 1024
EDITOR_FORMATS = ("plain", "escaped", "hex", "base64")
ELEMENT_TYPES = {2: "Cell", 3: "Line", 4: "Line string", 5: "Group data/color table", 6: "Shape", 7: "Text node", 8: "Digitizer data", 9: "Design file header", 10: "Level symbology", 11: "Curve", 12: "Complex string", 13: "Conic", 14: "Complex shape", 15: "Ellipse", 16: "Arc", 17: "Text", 18: "Surface", 19: "Solid", 21: "B-spline poles", 22: "Point string", 23: "Cone", 24: "B-spline surface", 25: "B-spline boundary", 26: "B-spline knots", 27: "B-spline curve", 28: "B-spline weights", 33: "Dimension", 34: "Shared cell definition", 35: "Shared cell instance", 36: "Multiline", 37: "Tag", 38: "DgnStore component", 39: "DgnStore header", 44: "Type 44", 66: "Application/database/startup data", 87: "Legacy raster header", 88: "Legacy raster component", 90: "Raster reference", 91: "Raster reference component", 92: "Raster hierarchy", 93: "Raster hierarchy component", 94: "Raster frame", 95: "Table entry", 96: "Table", 97: "View group", 98: "View", 99: "Level mask", 100: "Reference attachment", 101: "Matrix header", 102: "Matrix integer data", 103: "Matrix double data", 105: "Mesh", 106: "Extended graphic element", 107: "Extended non-graphic element", 108: "Reference override", 110: "Named group", 111: "Named group component", 112: "Legacy component instance", 113: "Legacy representation"}
ELEMENT_TYPES.update({1: "Cell library", 182: "Geographic coordinate system"})
TABLE_LEVELS = {
    1: "Levels", 2: "Fonts", 3: "Text styles", 4: "Filters",
    5: "Dimension styles", 6: "Multiline styles", 7: "Line style names",
    8: "Line style definitions", 9: "Dictionaries", 10: "Registered applications",
    11: "ColorBooks", 12: "Deprecated custom render modes", 16: "Symbol styles",
    17: "ColorBook data", 18: "Material palettes", 19: "Level names",
    20: "Animation parameters", 21: "Animation schedules", 22: "Render setups",
    23: "Light setups", 24: "Named presentations",
}
LINKAGE_NAMES = {
    20343: "TFLabel", 20357: "Node", 20372: "Cell definition", 20389: "ACS",
    20394: "Associated elements", 21038: "Embedded BRep", 22224: "Dependency",
    22226: "String", 22227: "BitMask", 22228: "Thickness", 22229: "Double array",
    22238: "Dimension extension", 22241: "Symbology", 22243: "XML",
    22244: "DWG XData", 22248: "Level library", 22251: "Raster metadata",
    22257: "Element ID array", 22271: "ECXAttributes", 22288: "MultiStateMask",
    22295: "Model ID", 22296: "Model handler", 45086: "OLE",
}
BUILDING_LINKAGES = {
    48640 + index: name for index, name in enumerate(
        "TFVERSION TMSVERSION TFSMARTSECT_DATA TFSMARTSECT_STREAM TFPARTREF "
        "TFIDUNIFYLIST TFHATCHANGLE TFDOCCONTEXT TFENTITYREP TFANNOTATION "
        "TFHATCHCELLNAME TFWALLSCHEDULEDATA TFDOORSCHEDULEDATA TFMASTERDEMDESCR "
        "TFPERFORATOR RBLDR AUTOANNORULE ROOF TFANNOTATIONEXT CURTAINWALL "
        "COLUMNGRIDHANDLER FLOORPICKERGRIDLIST COMPOUNDSLAB MODELMAPPED".split())
}
for _base, _names in (
    (48750, "ATFSPACES ATFELEMENT ATFELMCOMP ATFSPACELEGEND"),
    (48780, "ATFCEILING ATFCEILINGFIXTURE STAIRELEMENT FLIGHTELEMENT TREADELEMENT RISERELEMENT LANDINGELEMENT STRINGERELEMENT STAIRANNOTATIONELEMENT COMPOUNDFORMELEMENT ATFDGANNOTATIONCOMPONENTS ATFANNOTATIONELEVATION ATFANNOTATIONLABELCOORD"),
    (48800, "TMSDUCT TMSPIPE TMSGEOM TMSSECTMRK TMSDTAIL TMSPCP TMSTPCP TMSHCP TMSTHCP TMSLBL TMSWRKLN TMSCONN TMSDEV TMSID TMSOWN TMSCONNTO TMSSECT TMSOVRRD TMSINLINE TMSPARA TMSFLEX TMSTYPETAG TMSEQUIP TMSFITTING HVACENDDATA MODIFYTEXT MODIFYDIM HVACVULCANDATA MECHLABEL STACKEDANNO"),
    (48900, "STFPROFLINE STFNONLINEAR STFNODE STFBEAMELEMENT STFMODELANNOTE STFLOAD STFLOADCASE STFLOADCOMBINATION STFPLATE2D STFHOLE STFEXPORTMAP_V2 STFGRIDSYSTEMDATA STFGRIDSYSTEMLIST STFSTORYDATA ISMID OPENING MODIFIER RAILINGELEMENT HORIZONTALRAILELEMENT POSTELEMENT BALUSTERELEMENT REBARREINFORCEMENT JOIST JOISTTOPCHORD JOISTBOTTOMCHORD JOISTWEB STEELDECK COMPOSITEDECK JOISTENVELOPE SUBSTRUCTURE FIREPROOFING FIREPROOFINGID"),
):
    BUILDING_LINKAGES.update({_base + index: name for index, name in enumerate(_names.split())})
BUILDING_LINKAGES.update({
    48700: "TFID", 48701: "PICASSO", 48702: "UNIFICATION_CACHE",
    48742: "TFTYPE66", 48760: "ATFFLOORS", 48770: "ATFDGANNOTATION",
    48971: "STFGRIDSYSTEMMODEL", 48972: "STFDRAWINGDEPENDENCY",
    48974: "STFSTEELCOLUMNSCHEDULE", 48975: "STFCONCRETECOLUMNSCHEDULE",
    48976: "STFMAP", 48977: "STFGRIDSYSTEM", 48978: "STFELEVATIONGRID",
})
LINKAGE_NAMES.update(BUILDING_LINKAGES)
BECXML_MAGIC = bytes.fromhex("01424543584d4c00ff0a0d")
BECXML_VALUE_TYPES = {
    0xF0: "bool", 0xF1: "byte", 0xF2: "int16", 0xF3: "int32",
    0xF4: "int64", 0xF5: "point2d", 0xF6: "binary", 0xF7: "double",
    0xF8: "datetime", 0xF9: "point3d", 0xFA: "string8",
    0xFB: "string16", 0xFC: "string-ref", 0xFD: "array", 0xFE: "string-array",
}
PASSIVE_KINDS = frozenset({
    "dgn-design-header", "dgn-manifest", "dgn-model-index", "dgn-model-header",
    "dgn-becxml", "dgn-ecxd", "dgn-matrix", "dgn-store", "dgn-dependency",
    "dgn-bitmask", "dgn-multistate-mask", "dgn-native-core",
    "dgn-tflabel",
    "dgn-ecx-instance",
    "dgn-gcs",
})
RECORD_LAYOUTS = {
    100: {"component_count": (0, "I", True), "version": (4, "I", True), "group_id": (8, "I", False), "file_number": (12, "I", False), "parent_attachment_id": (16, "Q", True)},
    94: {"component_count": (0, "I", True), "version": (4, "I", True), "raster_flags": (8, "I", False), "transform": (16, "16d", False)},
    12: {"component_count": (0, "I", True)},
    14: {"component_count": (0, "I", True)},
    106: {"component_count": (0, "I", True)},
    107: {"component_count": (0, "I", True)},
}
STRING_LINKAGE_KEYS = dict(enumerate("Generic Name Description FileName LogicalName PatternCell DimensionStyle DimStyleDescr Library ProfileName LevelNameExpr LevelDescriptionExpr LevelColorExpr LevelStyleExpr LevelWeightExpr ElementColorExpr ElementStyleExpr ElementWeightExpr FileExpr MastUnitLabel SubUnitLabel ModelName SecondaryMastUnitLabel SecondarySubUnitLabel DimArrowCellName DimStrokeCellName DimDotCellName DimOriginCellName DimPrefixCellName DimSuffixCellName NameSpace FullReferencePath FilterMember XData ReportName RefAlternateFile RefAlternateModel RefAlternateFullPath DWGPatternName DWGMTextFile DWGDieselTextFile AlternateFontName DwgBlockName NamedGroupName NamedGroupDescription NamedGroupType ReferenceNamedGroup DefaultRefLogical ReferenceRevision DimNoteCellName ClipName GeoFeature GeoPbaName SheetFormName PaperFormName WindowsPrinterName PltFileName ColorBook AnimationParameter AnimationActionType AnimationOriginalActorName SchemaName EndField PstFileName ReferenceProviderID".split()))
STRING_LINKAGE_KEYS.update({66: "IlluminatedMesh", 67: "LevelColor", 68: "LevelElementColor", 69: "LevelStyle", 70: "LevelElementStyle", 71: "LevelMaterial", 72: "LevelElementMaterial", 73: "SheetName", 75: "EcInstance", 76: "ECOMConnectionLinkage", 77: "ComponentSetExpressionSummary", 78: "ECOMConnectionNamedGroupLinkage", 79: "ComponentSetExpression", 80: "SchemaVersion", 81: "CommonGeometryType", 82: "CommonGeometryOperation", 83: "PrintStyleName", 84: "SchemaProviderName", 85: "DwgEntityPropertyList", 86: "EmbeddedReference", 87: "ReferenceSymbologyTemplate", 88: "SheetIndexDefaultProperties", 89: "BackgroundMapJson", 90: "NamedPresentationCondition", 91: "TPFFileName", 92: "ItemType", 93: "Visibility"})
STRING_LINKAGE_KEYS[74] = "Sheet_UNUSED_74"
PLACEHOLDER_LINK_CHOICES = [
    ("DGN File", "File", "DgnFileSchema", ["DgnFileProperties"]),
    ("Model", "Model", "DgnModelSchema", ["GeneralModelProperties", "SheetModelProperties", "DrawingProperties"]),
    ("Reference", "Region", "DgnModelSchema", ["AttachmentModelProperties"]),
    ("Saved View", "Region", "DgnElementSchema", ["NamedViewElement"]),
    ("Drawing Boundary", "Region", "DgnElementSchema", ["DrawingTitleElement"]),
    ("Named Boundary", "Region", "DgnElementSchema", ["NamedBoundaryProperties"]),
    ("Configuration Variable", "System", "BentleyDesignLinksPresentation", ["ConfigurationVariableLinkProperties"]),
    ("File Link", "File", "BentleyDesignLinksPresentation", ["FileLinkProperties"]),
    ("Folder Link", "Folder", "BentleyDesignLinksPresentation", ["FolderLinkProperties"]),
    ("URL or Key-in", "Address", "BentleyDesignLinksPresentation", ["URLLinkProperties"]),
    ("Word Heading", "Region", "BentleyDesignLinksPresentation", ["WordHeadingLinkProperties"]),
    ("Word Bookmark", "Region", "BentleyDesignLinksPresentation", ["WordBookmarkLinkProperties"]),
    ("Excel Sheet", "Model", "BentleyDesignLinksPresentation", ["ExcelSheetLinkProperties"]),
    ("PDF Bookmark", "Region", "BentleyDesignLinksPresentation", ["PDFBookmarkLinkProperties"]),
    ("Link Set", None, "BentleyDesignLinksPresentation", ["LinkLinksetProperties"]),
]


def editor_encode(data: bytes, format: str) -> str:
    """Represent editor payloads; string representations always use strict UTF-8."""
    if format == "hex":
        return data.hex(" ")
    if format == "base64":
        return base64.b64encode(data).decode("ascii")
    if format in ("plain", "escaped"):
        text = data.decode("utf-8")
        return text if format == "plain" else json.dumps(text, ensure_ascii=True)[1:-1]
    raise ValueError("Unknown editor format")


def editor_decode(text: str, format: str, limit: int = EDITOR_LIMIT) -> bytes:
    """Strict, reversible parsing without evaluating content or guessing encodings."""
    if len(text) > limit * 6:
        raise ValueError(f"Editor payload exceeds {limit:,} bytes")
    if format == "plain":
        data = text.encode("utf-8")
    elif format == "escaped":
        result = []
        position = 0
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                   "a": "\a", "v": "\v", "\\": "\\", '"': '"', "'": "'", "/": "/"}
        while position < len(text):
            char = text[position]
            position += 1
            if char != "\\":
                result.append(char)
                continue
            if position == len(text):
                raise ValueError("Incomplete escape: use \\\\ for a literal backslash")
            escape = text[position]
            position += 1
            if escape in escapes:
                result.append(escapes[escape])
            elif escape in ("x", "u", "U"):
                count = {"x": 2, "u": 4, "U": 8}[escape]
                digits = text[position:position + count]
                if len(digits) != count or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                    raise ValueError(f"Invalid \\{escape} escape: expected {count} hex digits")
                point = int(digits, 16)
                position += count
                if 0xD800 <= point <= 0xDBFF and escape == "u":
                    pair = text[position:position + 6]
                    if not re.fullmatch(r"\\u[dD][c-fC-F][0-9a-fA-F]{2}", pair):
                        raise ValueError("High surrogate requires a matching \\uXXXX low surrogate")
                    point = 0x10000 + ((point - 0xD800) << 10) + int(pair[2:], 16) - 0xDC00
                    position += 6
                if point > 0x10FFFF or 0xD800 <= point <= 0xDFFF:
                    raise ValueError("Escape is not a Unicode scalar value")
                result.append(chr(point))
            else:
                raise ValueError(f"Unknown escape \\{escape}; use \\\\ for a literal backslash")
        data = "".join(result).encode("utf-8")
    elif format == "hex":
        compact = re.sub(r"[ \t\r\n\v\f]", "", text)
        if len(compact) % 2 or re.search(r"[^0-9a-fA-F]", compact):
            raise ValueError("Invalid hexadecimal: use pairs of hex digits, optionally spaced")
        data = bytes.fromhex(compact)
    elif format == "base64":
        compact = re.sub(r"[ \t\r\n\v\f]", "", text)
        try:
            data = base64.b64decode(compact.encode("ascii"), validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Invalid Base64: use the standard alphabet and correct padding") from error
        if base64.b64encode(data).decode("ascii") != compact:
            raise ValueError("Invalid Base64: non-canonical padding or trailing bits")
    else:
        raise ValueError("Unknown editor format")
    if len(data) > limit:
        raise ValueError(f"Editor payload exceeds {limit:,} bytes")
    return data


def editor_text(text: str, format: str, limit: int = EDITOR_LIMIT) -> str:
    try:
        return editor_decode(text, format, limit).decode("utf-8")
    except UnicodeError as error:
        raise ValueError("String fields require valid UTF-8 bytes; binary data can be inspected/exported, not staged") from error


def editor_plain_safe(text: str) -> bool:
    """Qt plain-text widgets normalize some controls; use escaped text for those."""
    return all(char.isprintable() or char in "\n\t" for char in text)


def field_choices() -> dict:
    return {
        "description": "Source-derived choices, not a file-target binding. Read-only catalogue; changing a field also requires compatible property metadata and dependencies.",
        "source": "sources/PowerPlatform/MstnPlatform/PPModules/TextTools/Apps/TextEditor/FieldEditor.cpp:949-1041",
        "field_type": "Placeholder Link Properties",
        "persistent_handler": "PlaceHolderLinkProp",
        "supported_existing_property": "Leaf.NodeName (Link Name) in BentleyDesignLinksPresentation with DgnLinkPropertyEnabler",
        "editing": "Compatible placeholder link types can change for this property. DGN File/Model/Reference/etc. need different property schemas. No real target is assigned; the app still treats the field as a placeholder.",
        "encoding_note": "Some link choices share the same persisted ancestor key and Leaf.NodeName property. matching_link_types lists possibilities; subtype identity cannot be recovered from these fields alone.",
        "link_types": [{"label": label, "ancestor_key": ancestor, "schema": schema, "classes": classes} for label, ancestor, schema, classes in PLACEHOLDER_LINK_CHOICES],
    }


def object_choices() -> dict:
    geometry = {2, 3, 4, 6, 11, 13, 15, 16, 21}
    return {"description": "Capabilities for editing existing records, not an all-feature DGN creator. Ranges, dependencies, checksums, signatures and cross-stream indexes are not globally repaired.", "element_types": [{"type": number, "name": label, "support": "text/field metadata" if number in (7, 17) else "geometry/header/linkages" if number in geometry else "fixed metadata/header/linkages; other payload raw" if number in RECORD_LAYOUTS or number == 66 else "header/linkages; type-specific payload raw"} for number, label in ELEMENT_TYPES.items()], "string_linkage_keys": STRING_LINKAGE_KEYS, "locations": "All writable files: WRITABLE.ro.md and writable-index.ro.json. Model objects: objects/. File-level objects: data/, with chunk_index in objects/index.ro.json. XAttributes: attributes/. Fields: fields/. Readable text/XML: content/, always UTF-8.", "sources": ["sources/PowerPlatform/DgnPlatform/PublicAPI/DgnPlatform/DgnPlatform.r.h:1970-2037", "sources/PowerPlatform/DgnPlatform/PublicAPI/DgnPlatform/DgnFileIO/DgnElements.h:243-980", "sources/PowerPlatform/DgnPlatform/DgnCore/Linkage.cpp:36-98", "sources/PowerPlatform/DgnPlatform/DgnFileIO/strlinkage.cpp:46-90"], "safety": "No reference, URL, command, application, embedded document or database connection is activated."}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finite_numbers(value: Any) -> bool:
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            pending.extend(child for key, child in node.items() if key != "original")
        elif isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, float) and not math.isfinite(node):
            return False
    return True


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def disk_name(name: str) -> str:
    encoded = quote(name, safe="#$^~@!()+,;=-")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if encoded.split(".")[0].upper() in reserved or encoded.startswith("."):
        encoded = f"%{ord(encoded[0]):02X}" + encoded[1:]
    while encoded.endswith("."):
        encoded = encoded[:-1] + "%2E"
    return encoded


def inside(folder: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise ValueError(f"Unsafe workspace path: {relative!r}")
    resolved = (folder / candidate).resolve()
    if not resolved.is_relative_to(folder.resolve()):
        raise ValueError(f"Workspace path escapes folder: {relative!r}")
    return resolved


def read_limited(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"File exceeds --max-mib: {path}")
    with path.open("rb") as handle:
        chunks = [handle.read(size + 1)]
        remaining = limit + 1 - len(chunks[0])
        while remaining and (chunk := handle.read(min(remaining, 65536))):
            chunks.append(chunk)
            remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > limit:
        raise ValueError(f"File exceeds --max-mib: {path}")
    return data


def inflate(data: bytes, limit: int) -> tuple[bytes, bytes] | None:
    inflater = zlib.decompressobj()
    try:
        payload = inflater.decompress(data, limit + 1)
    except zlib.error:
        return None
    if len(payload) > limit or inflater.unconsumed_tail:
        raise ValueError("Decompressed stream exceeds --max-mib")
    if not inflater.eof:
        return None
    return payload, inflater.unused_data


def decode_stream(names: list[str], raw: bytes, limit: int) -> tuple[str, bytes, bytes, bytes]:
    offset = 0
    if names == ["Dgn~H"]:
        if len(raw) < 20:
            raise ValueError("Truncated Dgn~H framing")
        if struct.unpack_from("<H", raw)[0] & 2:
            raise ValueError("Encrypted Dgn~H is unsupported")
        offset = 20
    elif names[-1].startswith("$") and len(raw) >= 16:
        flags = struct.unpack_from("<I", raw, 4)[0]
        if flags & 4:
            return "raw", raw, b"", b""
        if flags & 2:
            offset = 16
        else:
            return "framed-raw", raw[16:], raw[:16], b""
    decoded = inflate(raw[offset:], limit)
    if decoded is None:
        if offset == 20:
            if struct.unpack_from("<H", raw)[0] & 1:
                raise ValueError("Invalid compressed Dgn~H")
            return "framed-raw", raw[20:], raw[:20], b""
        return "raw", raw, b"", b""
    payload, suffix = decoded
    return "zlib", payload, raw[:offset], suffix


def ole_reader():
    try:
        import olefile
    except ImportError as error:
        raise RuntimeError("Install dependency: python -m pip install olefile") from error
    return olefile


def binary_view(data: bytes) -> dict:
    return {"kind": "opaque-bytes", "hex_rows": [data[offset:offset + 32].hex(" ") for offset in range(0, len(data), 32)]}


def binary_bytes(view: dict) -> bytes:
    if view["kind"] == "byte-string":
        if view["encoding"] not in {"latin-1", "utf-8", "utf-8-sig", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"}:
            raise ValueError("Unsupported byte-string encoding")
        return bytes.fromhex(view.get("bom_hex", "")) + view["text"].encode(view["encoding"])
    return bytes.fromhex(" ".join(view["hex_rows"]))


def readable_bytes(node: Any) -> Any:
    if isinstance(node, dict):
        if node.get("kind") == "opaque-bytes":
            data = binary_bytes(node)
            decoded = text_view(data)
            if decoded is not None:
                return {**decoded, "kind": "byte-string"}
            return {"kind": "byte-string", "encoding": "latin-1", "text": data.decode("latin-1")}
        return {key: readable_bytes(value) for key, value in node.items()}
    if isinstance(node, list):
        return [readable_bytes(value) for value in node]
    return node


def field_string(data: bytes, offset: int) -> tuple[str, int]:
    mode, count = struct.unpack_from("<BH", data, offset)
    length = count * (2 if mode == 0 else 1)
    start = offset + 3
    if mode not in (0, 1) or start + length > len(data):
        raise ValueError("Invalid persisted field string")
    return data[start:start + length].decode("utf-16-le" if mode == 0 else "latin-1"), start + length


def packed_field_string(text: str) -> bytes:
    if "\0" in text:
        raise ValueError("Field strings cannot contain NUL")
    narrow = all(ord(char) <= 255 for char in text)
    encoded = text.encode("latin-1" if narrow else "utf-16-le")
    count = len(encoded) if narrow else len(encoded) // 2
    if count > 65535:
        raise ValueError("Field string exceeds 16-bit length")
    return struct.pack("<BH", 1 if narrow else 0, count) + encoded


def field_dictionary(expression: str) -> dict:
    root = ET.fromstring("<FieldDictionary>" + expression + "</FieldDictionary>")
    result = {}
    for node in root:
        if node.tag in result or len(node) != 1 or node[0].tag != "String" or len(node[0]) or node.attrib or node[0].attrib:
            raise ValueError("Unsupported field dictionary entry")
        result[node.tag] = node[0].text or ""
    return result


def compatible_link_choices(handler: str, dictionary: dict) -> list[str]:
    if handler == "PlaceHolderLinkProp" and (dictionary.get("Schema"), dictionary.get("Class"), dictionary.get("Access"), dictionary.get("Enabler")) == ("BentleyDesignLinksPresentation", "Leaf", "NodeName", "DgnLinkPropertyEnabler"):
        return [label for label, ancestor, schema, classes in PLACEHOLDER_LINK_CHOICES if schema == "BentleyDesignLinksPresentation"]
    return []


def text_field_view(data: bytes) -> dict | None:
    if len(data) < 13:
        return None
    size, version, flags, state, reason = struct.unpack_from("<IBIHH", data)
    if size != len(data) or version != 1 or flags & ~0x1F:
        return None
    values = {}
    offset = 13
    try:
        for bit, key in ((1, "handler"), (2, "expression"), (4, "error_message"), (8, "formatter_name")):
            if flags & bit:
                values[key], offset = field_string(data, offset)
        formatter = b""
        if flags & 16:
            count = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            formatter = data[offset:offset + count]
            if len(formatter) != count:
                return None
            offset += count
        if offset != len(data) or "expression" not in values or "handler" not in values:
            return None
        dictionary = field_dictionary(values["expression"])
    except (ValueError, UnicodeError, struct.error, ET.ParseError):
        return None
    choices = compatible_link_choices(values["handler"], dictionary)
    ancestor = dictionary.get("DemoTargetLinkAncestorKey")
    matching = [label for label, key, schema, classes in PLACEHOLDER_LINK_CHOICES if label in choices and key == ancestor]
    current = matching[0] if len(matching) == 1 else None
    return {"kind": "dgn-text-field", "field_type": "Placeholder Link Properties" if values["handler"] == "PlaceHolderLinkProp" else values["handler"], "handler": values["handler"], "placeholder_link_type": current, "matching_link_types": matching, "compatible_link_types": choices, "dictionary": dictionary, "formatter_name": values.get("formatter_name", ""), "state_flags": state, "evaluation_flags": reason, "original": binary_view(data), "edit_warning": "Edit placeholder_link_type or dictionary.DisplayValue. Some link subtypes share identical stored keys; matching_link_types reports ambiguity. Handler/property/schema/formatter conversion is unsupported. This does not assign a target, resolve the placeholder, or remove the app's placeholder-field edit error."}


def text_field_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    old = text_field_view(original)
    if old is None:
        raise ValueError("Invalid original field data")
    for key in ("handler", "field_type", "formatter_name", "state_flags", "evaluation_flags"):
        if view[key] != old[key]:
            raise ValueError(f"Field {key} conversion is unsupported; use the DGN application")
    dictionary = dict(view["dictionary"])
    if {key: value for key, value in dictionary.items() if key != "DisplayValue"} != {key: value for key, value in old["dictionary"].items() if key != "DisplayValue"}:
        raise ValueError("Only dictionary.DisplayValue is directly editable; use placeholder_link_type for compatible link changes")
    selected = view["placeholder_link_type"]
    if selected != old["placeholder_link_type"]:
        allowed = compatible_link_choices(old["handler"], old["dictionary"])
        if selected not in allowed:
            raise ValueError(f"Incompatible placeholder link type {selected!r}; compatible choices: {allowed}")
        ancestor = next(key for label, key, schema, classes in PLACEHOLDER_LINK_CHOICES if label == selected)
        if ancestor is None:
            dictionary.pop("DemoTargetLinkAncestorKey", None)
        else:
            dictionary["DemoTargetLinkAncestorKey"] = ancestor
    if dictionary == old["dictionary"]:
        return original
    root = ET.Element("FieldDictionary")
    for key, value in dictionary.items():
        node = ET.SubElement(root, key)
        ET.SubElement(node, "String").text = value
    expression = "".join(ET.tostring(node, encoding="unicode", short_empty_elements=False) for node in root)
    size, version, flags, state, reason = struct.unpack_from("<IBIHH", original)
    output = bytearray(original[:13])
    offset = 13
    for bit, key in ((1, "handler"), (2, "expression"), (4, "error_message"), (8, "formatter_name")):
        if flags & bit:
            value, end = field_string(original, offset)
            output.extend(packed_field_string(expression) if key == "expression" else original[offset:end])
            offset = end
    output.extend(original[offset:])
    struct.pack_into("<I", output, 0, len(output))
    return bytes(output)


def text_view(data: bytes) -> dict | None:
    if not data:
        return None
    encodings = ["utf-8"]
    bom = b""
    if data.startswith(b"\xef\xbb\xbf"):
        encodings = ["utf-8-sig"]
    elif data.startswith((b"\xff\xfe\0\0", b"\0\0\xfe\xff")):
        bom, data = data[:4], data[4:]
        encodings = ["utf-32-le" if bom == b"\xff\xfe\0\0" else "utf-32-be"]
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        bom, data = data[:2], data[2:]
        encodings = ["utf-16-le" if bom == b"\xff\xfe" else "utf-16-be"]
    elif len(data) >= 8 and len(data) % 4 == 0 and all(data[offset::4].count(0) >= len(data) // 4 * 0.75 for offset in (1, 2, 3)):
        encodings = ["utf-32-le"]
    elif len(data) >= 8 and len(data) % 4 == 0 and all(data[offset::4].count(0) >= len(data) // 4 * 0.75 for offset in (0, 1, 2)):
        encodings = ["utf-32-be"]
    elif data.startswith(b"<\0"):
        encodings = ["utf-16-le"]
    elif data.startswith(b"\0<"):
        encodings = ["utf-16-be"]
    elif len(data) >= 4 and len(data) % 2 == 0 and b"\0" in data:
        pairs = len(data) // 2
        if data[1::2].count(0) >= pairs * 0.75:
            encodings.append("utf-16-le")
        elif data[::2].count(0) >= pairs * 0.75:
            encodings.append("utf-16-be")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeError:
            continue
        if any(not char.isprintable() and char not in "\r\n\t" for char in text):
            continue
        if text.encode(encoding) != data:
            continue
        kind = "text"
        if text.lstrip().startswith("<"):
            try:
                ET.fromstring(text)
            except ET.ParseError:
                continue
            kind = "xml"
        elif text.lstrip().startswith(("{", "[")):
            try:
                json.loads(text)
            except ValueError:
                pass
            else:
                kind = "json-text"
        result = {"kind": kind, "encoding": encoding, "text": text}
        if bom:
            result["bom_hex"] = bom.hex()
        return result
    return None


class BinaryCursor:
    def __init__(self, data: bytes, limit: int = DEFAULT_LIMIT):
        if len(data) > limit:
            raise ValueError("Binary payload exceeds limit")
        self.data, self.offset, self.limit = data, 0, limit

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.data) - self.offset:
            raise ValueError("Truncated binary record")
        start = self.offset
        self.offset += size
        return self.data[start:self.offset]

    def unpack(self, format: str):
        return struct.unpack(format, self.take(struct.calcsize(format)))

    def count(self, endian: str = "<") -> int:
        code = self.take(1)[0]
        if code < 0xF0:
            if code > self.limit:
                raise ValueError("Tagged count exceeds limit")
            return code
        formats = {0xF1: "B", 0xF2: "h", 0xF3: "i"}
        if code not in formats:
            raise ValueError("Unsupported tagged count")
        value = self.unpack(endian + formats[code])[0]
        if value < 0 or value > self.limit:
            raise ValueError("Invalid tagged count")
        return value

    def utf16z(self) -> str:
        start = self.offset
        while self.take(2) != b"\0\0":
            pass
        return self.data[start:self.offset - 2].decode("utf-16-le")


def xml_fragment_view(data: bytes, limit: int = DEFAULT_LIMIT) -> dict | None:
    if len(data) < 20:
        return None
    encoding, declared_size = struct.unpack_from("<2i", data)
    if encoding not in (1, 2) or not 8 <= declared_size <= limit:
        return None
    decoded = inflate(data[8:], limit) if encoding == 2 else (data[8:], b"")
    if decoded is None or decoded[1]:
        return None
    try:
        cursor = BinaryCursor(decoded[0], limit)
        total, schema_size = cursor.unpack("<Ii")
        if total > limit or not 0 <= schema_size <= limit:
            return None
        schema = cursor.utf16z()
        xml_size = cursor.unpack("<i")[0]
        if not 0 <= xml_size <= limit:
            return None
        text = cursor.utf16z()
        ET.fromstring(text)
    except (ValueError, UnicodeError, struct.error, ET.ParseError):
        return None
    return {
        "kind": "dgn-xml-fragment", "encoding_type": encoding,
        "schema_urn": schema, "declared_stream_size": declared_size,
        "declared_xml_data_size": total, "declared_schema_size": schema_size,
        "declared_text_size": xml_size,
        "payload": {"kind": "xml", "encoding": "utf-16-le", "text": text},
        "tail": binary_view(decoded[0][cursor.offset:]), "original": binary_view(data),
    }


def xml_fragment_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    old = xml_fragment_view(original, max(DEFAULT_LIMIT, len(original)))
    if old is None:
        raise ValueError("Invalid XML fragment snapshot")
    for key in ("encoding_type", "schema_urn", "declared_stream_size",
                "declared_xml_data_size", "declared_schema_size", "declared_text_size", "tail"):
        if readable_bytes(view[key]) != readable_bytes(old[key]):
            raise ValueError("XML fragment framing and schema are read-only")
    payload = view_bytes(view["payload"])
    old_payload = view_bytes(old["payload"])
    if payload == old_payload:
        return original
    if len(payload) != len(old_payload) and any(binary_bytes(old["tail"])):
        raise ValueError("Cannot resize XML fragment with unknown extension bytes")
    if view["payload"]["kind"] != "xml" or view["payload"]["encoding"] != "utf-16-le" or "\0" in view["payload"]["text"]:
        raise ValueError("XML fragment requires NUL-free UTF-16 XML")
    old_root, root = ET.fromstring(old["payload"]["text"]), ET.fromstring(view["payload"]["text"])
    if old_root.tag.split("}")[-1] in ("ECSchema", "DataGroup", "DataGroupInstances", "ElementFragments"):
        identities = {"appType", "catalogType", "catalogItem", "Schema", "schemaName", "version", "alias", "name", "Name", "id", "ID", "guid", "GUID"}

        def validate(before, after, depth=0):
            if depth >= 64 or before.tag != after.tag or len(before) != len(after) or before.attrib.keys() != after.attrib.keys():
                raise ValueError("Schema/DataGroup structure is read-only")
            if any(before.attrib[key] != after.attrib[key] for key in before.attrib if key in identities):
                raise ValueError("Schema/DataGroup identities are read-only")
            for old_child, child in zip(before, after):
                validate(old_child, child, depth + 1)

        validate(old_root, root)
    schema = view["schema_urn"].encode("utf-16-le") + b"\0\0"
    xml = payload + b"\0\0"
    body = struct.pack("<Ii", 12 + len(schema) + len(xml), len(schema))
    body += schema + struct.pack("<i", len(xml)) + xml + binary_bytes(view["tail"])
    return struct.pack("<2i", view["encoding_type"], len(body) + 8) + (zlib.compress(body) if view["encoding_type"] == 2 else body)


def becxml_view(data: bytes, limit: int = DEFAULT_LIMIT) -> dict | None:
    if not data.startswith(BECXML_MAGIC) or len(data) < 17:
        return None
    result = {"kind": "dgn-becxml", "version": list(data[11:14]),
              "flags1": data[14], "flags2": data[15], "compression": data[16],
              "original": binary_view(data), "tokens": [], "strings": [],
              "complete": False}
    if data[11:14] != b"\1\0\0" or data[16] != 0:
        result["diagnostic"] = "Unsupported BECXML version/compression; payload preserved"
        return result
    endian = "<" if data[14] & 1 else ">"
    character_encoding = "utf-16-le" if data[14] & 2 else "utf-16-be"
    cursor = BinaryCursor(data, limit)
    cursor.offset = 17
    formats = {0xF0: "B", 0xF1: "B", 0xF2: "h", 0xF3: "i",
               0xF4: "q", 0xF5: "2d", 0xF7: "d", 0xF8: "q", 0xF9: "3d"}

    def value():
        code = cursor.take(1)[0]
        item = {"type": BECXML_VALUE_TYPES.get(code, "small"), "code": code}
        if code < 0xF0:
            item["value"] = code
        elif code in formats:
            values = cursor.unpack(endian + formats[code])
            item["value"] = list(values) if len(values) > 1 else values[0]
            if code == 0xF0:
                if values[0] not in (0, 1):
                    raise ValueError("Invalid BECXML Boolean")
                item["value"] = bool(values[0])
            if any(isinstance(number, float) and not math.isfinite(number) for number in values):
                raise ValueError("Non-finite BECXML value")
        elif code in (0xFA, 0xFB, 0xF6):
            count = cursor.count(endian)
            raw = cursor.take(count * (2 if code == 0xFB else 1))
            item["value"] = binary_view(raw) if code == 0xF6 else raw.decode(character_encoding if code == 0xFB else "latin-1")
        elif code == 0xFC:
            item["index"] = cursor.count(endian)
        elif code in (0xFD, 0xFE):
            member = cursor.take(1)[0]
            count = cursor.count(endian)
            if member not in formats:
                raise ValueError("Unsupported BECXML array member")
            values = [cursor.unpack(endian + formats[member]) for _ in range(count)]
            if any(isinstance(number, float) and not math.isfinite(number) for part in values for number in part):
                raise ValueError("Non-finite BECXML array value")
            if member == 0xF0 and any(part[0] not in (0, 1) for part in values):
                raise ValueError("Invalid BECXML Boolean array")
            item.update({"member_code": member, "values": [list(part) if len(part) > 1 else part[0] for part in values]})
        else:
            raise ValueError("Unsupported BECXML value")
        return item

    stack, attributes, attribute_value = [], False, False
    try:
        while cursor.offset < len(data):
            start = cursor.offset
            code = cursor.take(1)[0]
            token = {"code": code, "offset": start}
            if code == 0x30:
                if result["tokens"]:
                    raise ValueError("Unexpected BECXML string table")
                count = cursor.count(endian)
                result["strings"] = [value() for _ in range(count)]
                if any(item["code"] not in (0xFA, 0xFB) for item in result["strings"]):
                    raise ValueError("Non-string BECXML table entry")
            elif code in (0, 1, 2, 3, 5, 0x11):
                token["index"] = cursor.count(endian)
                if code in (0, 1, 2, 3):
                    if attributes or len(stack) >= 64:
                        raise ValueError("Invalid BECXML element nesting")
                    if code in (1, 2, 3):
                        stack.append(code)
                    attributes = code in (1, 3)
                elif code == 5:
                    if not attributes or attribute_value:
                        raise ValueError("Invalid BECXML attribute")
                    attribute_value = True
                elif attribute_value:
                    attribute_value = False
            elif code == 0x10:
                token["value"] = value()
                if attribute_value:
                    attribute_value = False
            elif code == 4:
                if not stack or attributes:
                    raise ValueError("Unbalanced BECXML end token")
                stack.pop()
            elif code == 6:
                if not attributes or attribute_value:
                    raise ValueError("Invalid BECXML attribute list")
                attributes = False
                if stack[-1] == 1:
                    stack.pop()
            else:
                raise ValueError(f"Unsupported BECXML token 0x{code:02x}")
            token["length"] = cursor.offset - start
            result["tokens"].append(token)
        if stack or attributes or attribute_value:
            raise ValueError("Unclosed BECXML element")
    except (ValueError, UnicodeError, struct.error) as error:
        result["diagnostic"] = str(error)
        result["unparsed_offset"] = cursor.offset
        return result
    result["complete"] = True
    return result


def becxml_bytes(view: dict) -> bytes:
    return passive_bytes(view, becxml_view)


def ecxd_view(data: bytes, limit: int = DEFAULT_LIMIT) -> dict | None:
    if len(data) < 8 or len(data) > limit:
        return None
    schema, class_index, provider, flags, reserved = struct.unpack_from("<3H2B", data)
    size = 16 if flags & 1 else 8
    if len(data) < size:
        return None
    result = {"kind": "dgn-ecxd", "schema_index": schema, "class_index": class_index,
              "provider_id": provider, "flags": flags, "reserved": reserved,
              "read_only": bool(flags & 2), "hidden": bool(flags & 4),
              "payload": binary_view(data[size:]), "original": binary_view(data)}
    if size == 16:
        result["layout_major"], result["layout_minor"] = struct.unpack_from("<2I", data, 8)
    return result


def ecx_instance_view(data: bytes, handler: int, limit: int = DEFAULT_LIMIT) -> dict | None:
    if len(data) < 4 or struct.unpack_from("<I", data)[0] != 0x01010000:
        return None
    subtype = handler & 0xFFFF
    result = {"kind": "dgn-ecx-instance", "handler_id": handler, "version": 0x01010000,
              "subtype": subtype, "original": binary_view(data)}
    cursor = BinaryCursor(data, limit)
    cursor.offset = 4
    if subtype in (1, 3):
        try:
            result["schema_name"] = cursor.utf16z()
            result["schema_major"], result["schema_minor"] = cursor.unpack("<2I")
        except (ValueError, UnicodeError, struct.error):
            return None
        start = cursor.offset
    elif subtype in (0, 2):
        start = data.find(BECXML_MAGIC, 4)
        if start < 0:
            result["diagnostic"] = "Stored schema path is opaque; no BECXML body identified"
            return result
        result["schema_path"] = binary_view(data[4:start])
        result["note"] = "BECXML signature discovered after opaque schema path; schema target is not resolved"
    else:
        return None
    body = becxml_view(data[start:], limit)
    if body is None:
        return None
    result["payload"] = body
    return result


def passive_bytes(view: dict, decoder) -> bytes:
    def normalized(node):
        if isinstance(node, dict):
            return {key: normalized(value) for key, value in node.items() if key != "editing"}
        if isinstance(node, list):
            return [normalized(value) for value in node]
        return node

    original = binary_bytes(view["original"])
    expected = decoder(original)
    if expected is None or readable_bytes(normalized(view)) != readable_bytes(normalized(expected)):
        raise ValueError(f"{view['kind']} is read-only; native dependencies are not repaired")
    return original


def structured_text_metadata(view: dict, handler: int | None = None) -> dict:
    current = view
    while current.get("kind") in ("compressed-xattribute", "terminated-text", "dgn-xml-fragment"):
        current = current["payload"]
    if current.get("kind") == "xml":
        root = ET.fromstring(current["text"])
        name = root.tag.split("}")[-1]
        if name in ("ExtendedColors", "SolarLightMap", "LightProperties", "ECSchema",
                    "DataGroupInstances", "DataGroup", "ElementFragments"):
            view["format_name"] = name
        if name == "ECSchema":
            view["schema_name"] = root.attrib.get("schemaName", root.attrib.get("name", ""))
    elif current.get("kind") == "json-text" and handler == (22226 << 16 | 89):
        view["format_name"] = "Background Map JSON"
    return view


def attribute_payload_view(data: bytes, limit: int, handler: int | None = None, depth: int = 0) -> dict:
    if depth >= 16:
        return binary_view(data)
    if handler is not None:
        if handler >> 16 == 0xECDA:
            return ecxd_view(data, limit) or binary_view(data)
        if handler >> 16 == 22271:
            instance = ecx_instance_view(data, handler, limit)
            if instance:
                return instance
    fragment = xml_fragment_view(data, limit)
    if fragment is not None:
        return structured_text_metadata(fragment, handler)
    becxml = becxml_view(data, limit)
    if becxml is not None:
        return becxml
    direct = text_view(data)
    if direct is not None:
        return structured_text_metadata(direct, handler)
    if len(data) >= 8:
        compression, padding, size = struct.unpack_from("<2HI", data)
        if compression in (1, 2, 3) and size <= limit:
            decoded = inflate(data[8:], limit) if compression == 3 else (data[8:], b"")
            if decoded is not None and not decoded[1] and len(decoded[0]) == size:
                body = attribute_payload_view(decoded[0], limit, handler, depth + 1)
                return structured_text_metadata({"kind": "compressed-xattribute", "compression_type": compression, "padding": padding, "payload": body, "original": binary_view(data)}, handler)
    for count in (4, 2, 1):
        if data.endswith(b"\0" * count):
            text = text_view(data[:-count])
            if text is not None and count == (4 if text["encoding"].startswith("utf-32") else 2 if text["encoding"].startswith("utf-16") else 1):
                return structured_text_metadata({"kind": "terminated-text", "payload": text, "terminator_hex": "00" * count}, handler)
    return binary_view(data)


def attribute_sets_view(data: bytes, limit: int) -> dict | None:
    sets = []
    position = 0
    while position < len(data):
        if position + 28 > len(data):
            return None
        signature, size, set_type, reserved, element_id, count = struct.unpack_from("<4IQI", data, position)
        end = position + 28 + size
        if signature != 0xA11B or end > len(data) or count > 65535:
            return None
        cursor = position + 28
        attributes = []
        for index in range(count):
            if cursor + 16 > end:
                return None
            handler, attr_id, size_flags, attr_reserved = struct.unpack_from("<4I", data, cursor)
            length = size_flags & 0x7FFFFFFF
            cursor += 16
            if cursor + length > end:
                return None
            raw = data[cursor:cursor + length]
            decoded = text_field_view(raw) if handler == 0x57050000 and attr_id == 0 else None
            attributes.append({"handler_id": handler, "attribute_id": attr_id, "archive": bool(size_flags & 0x80000000), "reserved": attr_reserved, "payload": decoded or attribute_payload_view(raw, limit, handler)})
            cursor += length
        if cursor + 4 != end:
            return None
        flags = struct.unpack_from("<I", data, cursor)[0]
        sets.append({"signature": signature, "set_type": set_type, "reserved": reserved, "element_id": element_id, "flags": flags, "attributes": attributes})
        position = end
    return {"kind": "dgn-attribute-sets", "sets": sets}


def property_value(raw: bytes, codepage: int) -> dict | None:
    if len(raw) < 4:
        return None
    variant = struct.unpack_from("<I", raw)[0]
    formats = {2: "h", 3: "i", 4: "f", 5: "d", 11: "h", 16: "b", 17: "B", 18: "H", 19: "I", 20: "q", 21: "Q", 64: "Q"}
    value = None
    encoding = None
    if variant in formats and len(raw) >= 4 + struct.calcsize("<" + formats[variant]):
        value = struct.unpack_from("<" + formats[variant], raw, 4)[0]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if variant == 11:
            value = bool(value)
    elif variant in (30, 31) and len(raw) >= 8:
        count = struct.unpack_from("<I", raw, 4)[0]
        encoding = "utf-16-le" if variant == 31 or codepage == 1200 else ("utf-8" if codepage == 65001 else f"cp{codepage}")
        length = count * 2 if variant == 31 else count
        terminator = b"\0\0" if variant == 31 or codepage == 1200 else b"\0"
        text = raw[8:8 + length]
        if len(text) != length or not text.endswith(terminator):
            return None
        try:
            value = text[:-len(terminator)].decode(encoding)
        except (LookupError, UnicodeError):
            return None
    else:
        return None
    result = {"variant_type": variant, "value": value}
    if encoding:
        result["encoding"] = encoding
    return result


def property_spans(section: bytes) -> list[tuple[int, bytes]]:
    size, count = struct.unpack_from("<2I", section)
    if size != len(section) or 8 + count * 8 > size:
        raise ValueError("Invalid OLE property section")
    table = [struct.unpack_from("<2I", section, 8 + index * 8) for index in range(count)]
    offsets = sorted(offset for prop_id, offset in table)
    if len(set(offsets)) != len(offsets) or any(offset < 8 + count * 8 or offset >= size for offset in offsets):
        raise ValueError("Invalid OLE property offset")
    boundaries = dict(zip(offsets, offsets[1:] + [size]))
    return [(prop_id, section[offset:boundaries[offset]]) for prop_id, offset in table]


def properties_view(data: bytes) -> dict | None:
    if len(data) < 28 or data[:2] != b"\xfe\xff":
        return None
    count = struct.unpack_from("<I", data, 24)[0]
    if not 1 <= count <= 2 or 28 + count * 20 > len(data):
        return None
    sections = []
    names = {1: "CodePage", 2: "Title", 3: "Subject", 4: "Author", 5: "Keywords", 6: "Comments", 7: "Template", 8: "LastSavedBy", 9: "RevisionNumber", 10: "EditingTime_FILETIME", 11: "LastPrinted_FILETIME", 12: "Created_FILETIME", 13: "LastSaved_FILETIME", 14: "PageCount", 15: "WordCount", 16: "CharacterCount", 17: "Thumbnail", 18: "ApplicationName", 19: "Security"}
    for index in range(count):
        format_bytes = data[28 + index * 20:44 + index * 20]
        start = struct.unpack_from("<I", data, 44 + index * 20)[0]
        if start + 8 > len(data):
            return None
        size = struct.unpack_from("<I", data, start)[0]
        if start + size > len(data):
            return None
        raw = data[start:start + size]
        try:
            spans = property_spans(raw)
        except (ValueError, struct.error):
            return None
        codepage = next((struct.unpack_from("<H", value, 4)[0] for prop_id, value in spans if prop_id == 1 and len(value) >= 6), 1252)
        format_id = str(uuid.UUID(bytes_le=format_bytes))
        labels = names if format_id == "f29f85e0-4ff9-1068-ab91-08002b27b3d9" else {1: "CodePage", 2: "Category", 14: "Manager", 15: "Company"} if format_id == "d5cdd502-2e9c-101b-9397-08002b2cf9ae" else {1: "CodePage"}
        properties = []
        for prop_id, value in spans:
            decoded = property_value(value, codepage) if prop_id != 0 else None
            if decoded is not None:
                decoded.update({"kind": "ole-property-value", "original": binary_view(value), "codepage": codepage})
            properties.append({"id": prop_id, "name": labels.get(prop_id, f"Property_{prop_id}"), "payload": decoded or binary_view(value)})
        sections.append({"format_id": format_id, "properties": properties, "original": binary_view(raw)})
    return {"kind": "ole-properties", "header_hex": data[:24].hex(), "sections": sections, "original": binary_view(data)}


def properties_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    encoded_sections = []
    unchanged = bytes.fromhex(view["header_hex"]) == original[:24] and len(view["sections"]) == struct.unpack_from("<I", original, 24)[0]
    for index, section in enumerate(view["sections"]):
        old = binary_bytes(section["original"])
        entries = [(prop["id"], view_bytes(prop["payload"])) for prop in section["properties"]]
        if len({prop_id for prop_id, payload in entries}) != len(entries):
            raise ValueError("Duplicate OLE property ID")
        if entries == property_spans(old):
            encoded = old
        else:
            offset = 8 + 8 * len(entries)
            table = bytearray()
            payloads = bytearray()
            for prop_id, payload in entries:
                table.extend(struct.pack("<2I", prop_id, offset))
                padded = payload + b"\0" * (-len(payload) % 4)
                payloads.extend(padded)
                offset += len(padded)
            encoded = struct.pack("<2I", offset, len(entries)) + table + payloads
        format_bytes = uuid.UUID(section["format_id"]).bytes_le
        if unchanged:
            start = struct.unpack_from("<I", original, 44 + 20 * index)[0]
            old_size = struct.unpack_from("<I", original, start)[0]
            unchanged = encoded == original[start:start + old_size] and format_bytes == original[28 + 20 * index:44 + 20 * index]
        encoded_sections.append((format_bytes, encoded))
    if unchanged:
        return original
    header = bytes.fromhex(view["header_hex"])
    if len(header) != 24:
        raise ValueError("OLE property header must contain 24 bytes")
    offset = 28 + 20 * len(encoded_sections)
    table = bytearray()
    sections = bytearray()
    for format_bytes, encoded in encoded_sections:
        table.extend(format_bytes + struct.pack("<I", offset))
        sections.extend(encoded)
        offset += len(encoded)
    old_count = struct.unpack_from("<I", original, 24)[0]
    old_end = max(struct.unpack_from("<I", original, 44 + 20 * index)[0] + struct.unpack_from("<I", original, struct.unpack_from("<I", original, 44 + 20 * index)[0])[0] for index in range(old_count))
    return header + struct.pack("<I", len(encoded_sections)) + table + sections + original[old_end:]


def varichar_view(data: bytes) -> dict:
    if data.startswith(b"\xff\xfe\x01\x00"):
        return {"kind": "dgn-varichar", "mode": "unicode-narrow", "text": data[4:].decode("latin-1")}
    if data.startswith(b"\xff\xfe") and len(data) % 2 == 0:
        try:
            return {"kind": "dgn-varichar", "mode": "unicode-wide", "text": data[2:].decode("utf-16-le")}
        except UnicodeError:
            return binary_view(data)
    if not data.startswith((b"\xff\xfd", b"\xfd\xff", b"\xfe\xff")) and all(32 <= value < 127 for value in data):
        return {"kind": "dgn-varichar", "mode": "ascii-font-codes", "text": data.decode("ascii"), "note": "Font-specific glyph codes, not a verified Unicode mapping. ASCII edits only."}
    return binary_view(data)


def linkage_payload_view(data: bytes, primary: int) -> dict:
    result = {"original": binary_view(data)}
    if primary == 22227 and len(data) >= 12:
        key, flags, bits, count = struct.unpack_from("<2H2I", data)
        if count <= (len(data) - 12) // 2 and bits <= count * 16:
            result.update({"kind": "dgn-bitmask", "key": key, "flags": flags,
                           "default": bool(flags & 1), "valid_bits": bits,
                           "shorts": list(struct.unpack_from("<" + "H" * count, data, 12))})
    elif primary == 22288 and len(data) >= 16:
        key, width, default, reserved, states, count = struct.unpack_from("<4H2I", data)
        if 0 < width <= 16 and default < 1 << width and count <= (len(data) - 16) // 2 and states * width <= count * 16:
            result.update({"kind": "dgn-multistate-mask", "key": key, "bits_per_state": width,
                           "default": default, "reserved": reserved, "state_count": states,
                           "shorts": list(struct.unpack_from("<" + "H" * count, data, 16))})
    elif primary == 22241 and len(data) >= 20:
        key, overrides, style, weight, color, level = struct.unpack_from("<2Hi3I", data)
        result.update({"kind": "dgn-symbology", "key": key, "overrides": overrides,
                       "style": style, "weight": weight, "color": color, "level": level})
    elif primary == 22224 and len(data) >= 8:
        app, value, flags, count = struct.unpack_from("<4H", data)
        root_type = flags >> 10 & 15
        sizes = {0: 8, 1: 16, 2: 40, 3: 48, 4: 16, 5: 24, 7: 24, 8: 16}
        size = sizes.get(root_type)
        if size is not None and count <= (len(data) - 8) // size:
            roots = []
            for index in range(count):
                raw = data[8 + index * size:8 + (index + 1) * size]
                root = {"raw": binary_view(raw)}
                if root_type in (0, 1, 4, 5):
                    root["element_id"] = struct.unpack_from("<Q", raw)[0]
                    if root_type in (1, 5):
                        root_value = struct.unpack_from("<d", raw, 8)[0]
                        if math.isfinite(root_value):
                            root["value"] = root_value
                        else:
                            root["note"] = "Non-finite dependency value retained as bytes"
                    if root_type in (4, 5):
                        root["attachment_id"] = struct.unpack_from("<Q", raw, size - 8)[0]
                elif root_type == 8:
                    root["model_id"], root["value"], root["element_id"] = struct.unpack("<IiQ", raw)
                roots.append(root)
            result.update({"kind": "dgn-dependency", "application_id": app, "application_value": value,
                           "flags": flags, "root_type": root_type, "copy_options": flags >> 8 & 3, "roots": roots})
        elif root_type == 6 and count == 1:
            result.update({"kind": "dgn-dependency", "application_id": app, "application_value": value,
                           "flags": flags, "root_type": root_type, "copy_options": flags >> 8 & 3,
                           "roots": [{"raw": binary_view(data[8:])}], "note": "Variable-length path retained without target resolution"})
    elif primary == 22243 and len(data) >= 12:
        linkage_type, app, app_type, reserved, size = struct.unpack_from("<4HI", data)
        if size <= len(data) - 12:
            fragment = xml_fragment_view(data[12:12 + size])
            if fragment:
                result.update({"kind": "dgn-xml-linkage", "linkage_type": linkage_type,
                               "application_id": app, "application_type": app_type, "reserved": reserved,
                               "payload": fragment, "tail": binary_view(data[12 + size:])})
    elif primary == 22244:
        return xdata_view(data) or binary_view(data)
    elif primary == 20343:
        return tflabel_view(data) or binary_view(data)
    return result if "kind" in result else binary_view(data)


def xdata_view(data: bytes) -> dict | None:
    if len(data) < 4:
        return None
    size = struct.unpack_from("<I", data)[0]
    if size > len(data) - 4:
        return None
    records, offset = [], 4
    end = 4 + size
    while offset < end:
        if end - offset < 8:
            return None
        group, length, filler = struct.unpack_from("<hHI", data, offset)
        offset += 8
        if length > end - offset:
            return None
        raw = data[offset:offset + length]
        record = {"group": group, "filler": filler, "raw": binary_view(raw)}
        formats = {1010: "3d", 1011: "3d", 1012: "3d", 1013: "3d",
                   1040: "d", 1041: "d", 1042: "d", 1070: "h", 1071: "i"}
        if group in (1001, 1005) and length == 8:
            record["value"] = int.from_bytes(raw, "big")
        elif group in (1000, 1002, 1003) and raw.isascii() and b"\0" not in raw:
            record["value"] = raw.decode("ascii")
        elif group in formats and length == struct.calcsize("<" + formats[group]):
            values = struct.unpack("<" + formats[group], raw)
            if not all(not isinstance(value, float) or math.isfinite(value) for value in values):
                return None
            record["value"] = list(values) if len(values) > 1 else values[0]
        records.append(record)
        offset += length
    return {"kind": "dgn-xdata", "records": records, "tail": binary_view(data[end:]),
            "original": binary_view(data), "note": "Application/handle IDs are file-local and read-only; legacy strings admit ASCII edits only"}


def symbology_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    old = linkage_payload_view(original, 22241)
    if old.get("kind") != "dgn-symbology":
        raise ValueError("Invalid symbology linkage")
    for key in old:
        if key not in ("weight", "original") and view[key] != old[key]:
            raise ValueError("Symbology references, keys and override flags are read-only")
    if view["weight"] == old["weight"]:
        return original
    if type(view["weight"]) is not int or not 0 <= view["weight"] <= 31:
        raise ValueError("Symbology line weight must be an integer in 0–31")
    result = bytearray(original)
    struct.pack_into("<I", result, 8, view["weight"])
    return bytes(result)


def xdata_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    old = xdata_view(original)
    if old is None or len(view["records"]) != len(old["records"]):
        raise ValueError("XData record structure is read-only")
    output = bytearray()
    for item, previous in zip(view["records"], old["records"]):
        if item["group"] != previous["group"] or item["filler"] != previous["filler"] or binary_bytes(item["raw"]) != binary_bytes(previous["raw"]):
            raise ValueError("XData identity, padding and raw bytes are read-only")
        raw = binary_bytes(item["raw"])
        if item.get("value") != previous.get("value"):
            group = item["group"]
            if group == 1000:
                raw = item["value"].encode("ascii")
                if b"\0" in raw:
                    raise ValueError("XData strings cannot contain NUL")
            elif group in (1040, 1041, 1042, 1070, 1071):
                if type(item["value"]) not in (int, float) or not math.isfinite(item["value"]):
                    raise ValueError("Invalid XData scalar")
                raw = struct.pack("<" + ({1070: "h", 1071: "i"}.get(group, "d")), item["value"])
            else:
                raise ValueError("XData application, handle, control and reference fields are read-only")
        output.extend(struct.pack("<hHI", item["group"], len(raw), item["filler"]) + raw)
    if binary_bytes(view["tail"]) != binary_bytes(old["tail"]):
        raise ValueError("XData extension bytes are read-only")
    if len(output) != len(original) - 4 - len(binary_bytes(old["tail"])) and any(binary_bytes(old["tail"])):
        raise ValueError("Cannot resize XData with unknown extension bytes")
    result = struct.pack("<I", len(output)) + output + binary_bytes(view["tail"])
    return result + b"\0" * (-len(result) % 2)


def tflabel_view(data: bytes) -> dict | None:
    if len(data) < 61 or data[6] not in (5, 6, 7):
        return None
    version = data[6]
    needed = {5: 61, 6: 73, 7: 75}[version]
    if len(data) < needed:
        return None
    family, name = data[7:16].split(b"\0", 1)[0], data[16:57].split(b"\0", 1)[0]
    result = {"kind": "dgn-tflabel", "version": version,
              "element_class": struct.unpack_from("<h", data, 4)[0],
              "family": family.decode("ascii") if family.isascii() else binary_view(family),
              "part": name.decode("ascii") if name.isascii() else binary_view(name),
              "time": struct.unpack_from("<i", data, 57)[0], "original": binary_view(data)}
    if version >= 6:
        start = 63 if version == 7 else 61
        result["functional_bytes"] = list(data[start:start + 8])
        result["subtype"] = struct.unpack_from("<i", data, start + 8)[0]
    if version == 7:
        result["application_id"] = struct.unpack_from("<H", data, 61)[0]
    return result


def linkages_view(data: bytes) -> dict:
    records = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            return binary_view(data)
        header, primary = struct.unpack_from("<2H", data, offset)
        user = bool(header & 0x1000)
        words = ((header & 255) << ((header >> 8) & 15)) if user and header & 0x4000 else ((header & 255) + 1 if user else 4)
        end = offset + words * 2
        if words < 2 or end > len(data):
            return binary_view(data)
        raw = data[offset:end]
        record = {"kind": "dgn-linkage", "primary_id": primary, "header_flags": header & 0xF000, "original": binary_view(raw), "payload": linkage_payload_view(raw[4:], primary) if user else binary_view(raw[4:])}
        record["primary_name"] = LINKAGE_NAMES.get(primary, "Building/application linkage" if 48640 <= primary <= 48979 else "Unknown")
        if user and primary == 0x56D2 and len(raw) >= 12:
            key, padding, count = struct.unpack_from("<2HI", raw, 4)
            if 12 + count <= len(raw):
                record["payload"] = {"kind": "dgn-string-linkage", "key": key, "key_name": STRING_LINKAGE_KEYS.get(key, "Unknown"), "padding": padding, "string": varichar_view(raw[12:12 + count]), "tail": binary_view(raw[12 + count:]), "original": binary_view(raw[4:])}
        records.append(record)
        offset = end
    return {"kind": "dgn-linkages", "records": records}


def linkage_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    payload = view_bytes(view["payload"])
    flags = view["header_flags"]
    primary = view["primary_id"]
    old_header, old_primary = struct.unpack_from("<2H", original)
    if (flags, primary, payload) == (old_header & 0xF000, old_primary, original[4:]):
        return original
    if flags & ~0xF000 or len(payload) % 2:
        raise ValueError("Invalid linkage flags or odd payload length")
    if not flags & 0x1000:
        if len(payload) != 4:
            raise ValueError("Legacy DMRS linkages have a fixed eight-byte total size")
        return struct.pack("<2H", (old_header & 0xFFF) | flags, primary) + payload
    words = (len(payload) + 4 + 7) // 8 * 4
    if words >= 32768:
        raise ValueError("Linkage exceeds supported element word limit")
    exponent = 0
    mantissa = words
    if words > 256:
        while mantissa > 255:
            exponent += 1
            mantissa = (mantissa + 1) // 2
        mantissa = (words + (1 << exponent) - 1) >> exponent
        flags |= 0x4000
        words = mantissa << exponent
    else:
        flags &= ~0x4000
        mantissa = words - 1
    return struct.pack("<2H", flags | (exponent << 8) | mantissa, primary) + payload + b"\0" * (words * 2 - 4 - len(payload))


def string_linkage_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    value = view_bytes(view["string"])
    old_key, old_padding, old_count = struct.unpack_from("<2HI", original)
    if (view["key"], view["padding"], value, view_bytes(view["tail"])) == (old_key, old_padding, original[8:8 + old_count], original[8 + old_count:]):
        return original
    if view["key"] != old_key or view["padding"] != old_padding:
        raise ValueError("String linkage key and padding are read-only")
    if old_key == 62:
        raise ValueError("EndField linkage is a structural text-field marker, not editable text")
    if old_key == 89:
        text = view["string"].get("text")
        if text is not None:
            json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite map JSON")))
    result = struct.pack("<2HI", old_key, old_padding, len(value)) + value
    if len(value) == old_count:
        return result + view_bytes(view["tail"])
    if any(original[8 + old_count:]):
        raise ValueError("String linkage has additional non-padding data; resizing is unsupported")
    return result + b"\0" * (-len(result) % 2)


def text_element_view(body: bytes, element_type: int, flags: int) -> dict | None:
    if element_type not in (7, 17) or not flags & 0x1000 or len(body) < 162:
        return None
    is3d = bool(struct.unpack_from("<H", body, 32)[0] & 0x800)
    string_offset = 194 if is3d else 162
    header_size = string_offset if element_type == 17 else string_offset - 2
    attr_offset = struct.unpack_from("<I", body)[0] * 2 - 8
    if len(body) < header_size or not header_size <= attr_offset <= len(body):
        return None
    fields = {"kind": "dgn-text-element" if element_type == 17 else "dgn-text-node", "is_3d": is3d, "element_id": struct.unpack_from("<Q", body, 8)[0], "level_id": struct.unpack_from("<I", body, 4)[0], "original": binary_view(body)}
    fields["origin"] = list(struct.unpack_from("<3d" if is3d else "<2d", body, 168 if is3d else 144))
    fields["orientation"] = list(struct.unpack_from("<4d" if is3d else "<d", body, 136))
    fields["linkages"] = linkages_view(body[attr_offset:])
    if element_type == 7:
        component_count, node_number, font, maximum, justification = struct.unpack_from("<3I2H", body, 96)
        fields.update({"component_count": component_count, "node_number": node_number, "font_id": font, "maximum_length": maximum, "justification": justification, "line_spacing": struct.unpack_from("<d", body, 112)[0], "width_multiplier": struct.unpack_from("<d", body, 120)[0], "height_multiplier": struct.unpack_from("<d", body, 128)[0]})
    else:
        font, justification, byte_count = struct.unpack_from("<I2H", body, 96)
        edfields = struct.unpack_from("<H", body, string_offset - 2)[0]
        if string_offset + byte_count > attr_offset:
            return None
        fields.update({"font_id": font, "justification": justification, "width_multiplier": struct.unpack_from("<d", body, 104)[0], "height_multiplier": struct.unpack_from("<d", body, 112)[0], "stored_width": struct.unpack_from("<d", body, 120)[0], "stored_height": struct.unpack_from("<d", body, 128)[0], "enter_data_fields": edfields, "string": varichar_view(body[string_offset:string_offset + byte_count]), "edit_warning": "Text changes preserve stored extents/range and rich-text/field metadata. Validate layout in OpenBuildings; enter-data-field text resizing is rejected."})
    return fields if finite_numbers(fields) else None


def text_element_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    result = bytearray(original)

    def finish(data: bytes | bytearray) -> bytes:
        if "linkages" not in view:
            return bytes(data)
        attr_offset = struct.unpack_from("<I", data)[0] * 2 - 8
        return bytes(data[:attr_offset]) + view_bytes(view["linkages"])
    is3d = view["is_3d"]
    original_is3d = bool(struct.unpack_from("<H", original, 32)[0] & 0x800)
    if is3d != original_is3d:
        raise ValueError("Changing text dimensionality requires conversion by the DGN application")
    struct.pack_into("<I", result, 4, view["level_id"])
    if view["element_id"] != struct.unpack_from("<Q", original, 8)[0]:
        raise ValueError("Text element IDs are read-only because other records reference them")
    struct.pack_into("<3d" if is3d else "<2d", result, 168 if is3d else 144, *view["origin"])
    struct.pack_into("<4d" if is3d else "<d", result, 136, *view["orientation"])
    if view["kind"] == "dgn-text-node":
        if view["component_count"] != struct.unpack_from("<I", original, 96)[0]:
            raise ValueError("Text-node component count is read-only; edit existing children")
        struct.pack_into("<3I2H", result, 96, view["component_count"], view["node_number"], view["font_id"], view["maximum_length"], view["justification"])
        struct.pack_into("<3d", result, 112, view["line_spacing"], view["width_multiplier"], view["height_multiplier"])
        return finish(result)
    offset = 194 if is3d else 162
    old_count = struct.unpack_from("<H", original, 102)[0]
    edfields = struct.unpack_from("<H", original, offset - 2)[0]
    if view["enter_data_fields"] != edfields:
        raise ValueError("Enter-data-field count is read-only")
    text = view_bytes(view["string"])
    if len(text) > 65535:
        raise ValueError("DGN text exceeds its 16-bit stored byte count")
    if len(text) != old_count and edfields:
        raise ValueError("Resizing text with enter-data fields requires the DGN application")
    struct.pack_into("<I2H", result, 96, view["font_id"], view["justification"], len(text))
    struct.pack_into("<4d", result, 104, view["width_multiplier"], view["height_multiplier"], view["stored_width"], view["stored_height"])
    if len(text) == old_count:
        result[offset:offset + old_count] = text
        return finish(result)
    attr_offset = struct.unpack_from("<I", original)[0] * 2 - 8
    tail = original[offset + old_count:attr_offset]
    if len(tail) > 1:
        raise ValueError("Text has additional core data; resizing requires the DGN application")
    result = result[:offset] + text
    if len(result) % 2:
        result += b"\0"
    new_attr_offset = (len(result) + 8) // 2
    result += original[attr_offset:]
    struct.pack_into("<I", result, 0, new_attr_offset)
    return finish(result)


def geometry_view(core: bytes, element_type: int, is3d: bool) -> dict | None:
    dimensions = 3 if is3d else 2
    point_bytes = dimensions * 8
    result = {"kind": "dgn-geometry", "element_type": element_type, "dimensions": dimensions, "original": binary_view(core)}
    if element_type == 3 and len(core) >= point_bytes * 2:
        result.update({"shape": "line", "start": list(struct.unpack_from("<" + "d" * dimensions, core)), "end": list(struct.unpack_from("<" + "d" * dimensions, core, point_bytes))})
    elif element_type in (4, 6, 11, 13, 21) and len(core) >= 8:
        count = struct.unpack_from("<I", core)[0]
        if count > (len(core) - 8) // point_bytes:
            return None
        result.update({"shape": "points", "points": [list(struct.unpack_from("<" + "d" * dimensions, core, 8 + index * point_bytes)) for index in range(count)], "tail": binary_view(core[8 + count * point_bytes:])})
    elif element_type in (15, 16):
        scalar_names = ["primary_axis", "secondary_axis"] if element_type == 15 else ["start_angle", "sweep_angle", "primary_axis", "secondary_axis"]
        orientation_count = 4 if is3d else 1
        total = (len(scalar_names) + orientation_count + dimensions) * 8
        if len(core) < total:
            return None
        result.update({"shape": "ellipse" if element_type == 15 else "arc", "orientation": list(struct.unpack_from("<" + "d" * orientation_count, core, len(scalar_names) * 8)), "origin": list(struct.unpack_from("<" + "d" * dimensions, core, (len(scalar_names) + orientation_count) * 8))})
        result.update({name: struct.unpack_from("<d", core, index * 8)[0] for index, name in enumerate(scalar_names)})
    elif element_type == 2:
        total = 8 + (dimensions * 3 + dimensions * dimensions) * 8
        if len(core) < total:
            return None
        result.update({"shape": "cell", "component_count": struct.unpack_from("<I", core)[0], "class_map": struct.unpack_from("<H", core, 4)[0], "cell_flags": struct.unpack_from("<H", core, 6)[0], "range_low": list(struct.unpack_from("<" + "d" * dimensions, core, 8)), "range_high": list(struct.unpack_from("<" + "d" * dimensions, core, 8 + point_bytes)), "transform": list(struct.unpack_from("<" + "d" * (dimensions * dimensions), core, 8 + 2 * point_bytes)), "origin": list(struct.unpack_from("<" + "d" * dimensions, core, 8 + 2 * point_bytes + dimensions * dimensions * 8))})
    else:
        return None
    return result if finite_numbers(result) else None


def geometry_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    element_type = view["element_type"]
    dimensions = view["dimensions"]
    old = geometry_view(original, element_type, dimensions == 3)
    if old is None or dimensions not in (2, 3) or view["shape"] != old["shape"]:
        raise ValueError("Invalid geometry representation")
    output = bytearray(original)

    def vector(offset: int, name: str, count: int) -> None:
        values = view[name]
        if len(values) != count:
            raise ValueError(f"Geometry {name} requires {count} values")
        struct.pack_into("<" + "d" * count, output, offset, *values)

    if view["shape"] == "line":
        vector(0, "start", dimensions)
        vector(dimensions * 8, "end", dimensions)
    elif view["shape"] == "points":
        points = view["points"]
        if element_type == 21 and len(points) != len(old["points"]):
            raise ValueError("B-spline pole count changes require matching parent spline metadata")
        if any(len(point) != dimensions for point in points):
            raise ValueError("Geometry point has the wrong dimensionality")
        if element_type == 6 and points != old["points"] and (len(points) < 4 or points[0] != points[-1]):
            raise ValueError("Shape points must contain a closed ring with at least four vertices")
        output = bytearray(struct.pack("<I", len(points)) + original[4:8])
        for point in points:
            output.extend(struct.pack("<" + "d" * dimensions, *point))
        output.extend(view_bytes(view["tail"]))
    elif view["shape"] in ("ellipse", "arc"):
        names = ["primary_axis", "secondary_axis"] if element_type == 15 else ["start_angle", "sweep_angle", "primary_axis", "secondary_axis"]
        for index, name in enumerate(names):
            struct.pack_into("<d", output, index * 8, view[name])
        orientation_count = 4 if dimensions == 3 else 1
        vector(len(names) * 8, "orientation", orientation_count)
        vector((len(names) + orientation_count) * 8, "origin", dimensions)
    elif view["shape"] == "cell":
        if view["component_count"] != old["component_count"]:
            raise ValueError("Cell component count is read-only; edit existing children")
        struct.pack_into("<2H", output, 4, view["class_map"], view["cell_flags"])
        vector(8, "range_low", dimensions)
        vector(8 + dimensions * 8, "range_high", dimensions)
        vector(8 + dimensions * 16, "transform", dimensions * dimensions)
        vector(8 + (dimensions * 2 + dimensions * dimensions) * 8, "origin", dimensions)
    return bytes(output)


def table_record_view(core: bytes, element_type: int, level: int) -> dict | None:
    if element_type not in (95, 96) or len(core) < (4 if element_type == 96 else 8):
        return None
    result = {"kind": "dgn-table-header" if element_type == 96 else "dgn-table-entry",
              "element_type": element_type, "table_level": level,
              "table_name": TABLE_LEVELS.get(level, "Unknown table"), "original": binary_view(core)}
    if element_type == 96:
        result["component_count"] = struct.unpack_from("<I", core)[0]
    elif level == 9:
        result["deprecated_item_id"] = struct.unpack_from("<Q", core)[0]
    elif level == 10:
        result["application_flags"] = struct.unpack_from("<I", core)[0]
    elif level == 11:
        result["entry_id"] = struct.unpack_from("<I", core)[0]
        result["color_bytes"] = binary_view(core[4:8])
    else:
        result["entry_id"], result["parent_id"] = struct.unpack_from("<2I", core)
        if level == 2 and len(core) >= 14:
            font, count = struct.unpack_from("<IH", core, 8)
            if count % 2 == 0 and count <= len(core) - 14:
                try:
                    name = core[14:14 + count].decode("utf-16-le")
                except UnicodeError:
                    pass
                else:
                    result.update({"font_number": font, "name": name.rstrip("\0"),
                                   "name_terminated": name.endswith("\0"),
                                   "terminator_count": len(name) - len(name.rstrip("\0")),
                                   "tail": binary_view(core[14 + count:])})
    return result


def table_record_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    old = table_record_view(original, view["element_type"], view["table_level"])
    if old is None:
        raise ValueError("Invalid metadata table")
    for key in old:
        if key not in ("name", "original") and readable_bytes(view[key]) != readable_bytes(old[key]):
            raise ValueError("Table identities and unsupported fields are read-only")
    if view.get("name") == old.get("name"):
        return original
    if old.get("table_level") != 2 or "name" not in old or "\0" in view["name"]:
        raise ValueError("Only supported font names admit replacement")
    name = (view["name"] + "\0" * old["terminator_count"]).encode("utf-16-le")
    tail = binary_bytes(old["tail"])
    count = struct.unpack_from("<H", original, 12)[0]
    if len(name) != count and any(tail):
        raise ValueError("Font entry has unknown extension bytes; resizing is unsupported")
    return original[:12] + struct.pack("<H", len(name)) + name + tail


def matrix_view(core: bytes, element_type: int) -> dict | None:
    minimum = 96 if element_type == 101 else 88
    if element_type not in (101, 102, 103) or len(core) < minimum:
        return None
    result = {"kind": "dgn-matrix", "element_type": element_type, "original": binary_view(core)}
    if element_type == 101:
        result["component_count"] = struct.unpack_from("<I", core)[0]
        result["version"] = struct.unpack_from("<H", core, 4)[0]
        result.update(zip(("values_per_struct", "structs_per_row", "tag", "index_family", "indexed_by"), struct.unpack_from("<5I", core, 76)))
    else:
        result["version"] = struct.unpack_from("<H", core)[0]
        capacity, count, transform, reserved = struct.unpack_from("<4I", core, 72)
        format = "i" if element_type == 102 else "d"
        size = struct.calcsize("<" + format)
        if count > capacity or capacity > (len(core) - 88) // size:
            return None
        values = list(struct.unpack_from("<" + format * count, core, 88))
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            return None
        result.update({"capacity": capacity, "count": count, "transform_type": transform, "values": values,
                       "unused": binary_view(core[88 + count * size:])})
    return result


def dgn_store_view(core: bytes, element_type: int) -> dict | None:
    size = 28 if element_type == 39 else 8
    if element_type not in (38, 39) or len(core) < size:
        return None
    result = {"kind": "dgn-store", "element_type": element_type, "original": binary_view(core)}
    if element_type == 39:
        names = ("component_count", "sequence", "store_id", "application_id", "checksum", "total_size", "data_size")
        result.update(zip(names, struct.unpack_from("<7I", core)))
        # C++ multichar IDs are numeric constants, not asserted byte spellings.
        roles = {int.from_bytes(name.encode("ascii"), "big"): name for name in
                 ("XMLf", "BRep", "BRpt", "BRdt", "Adfm", "tSet", "Ole ", "OleS", "MSet", "Ver1", "dStr")}
        result["store_role"] = roles.get(result["store_id"], "Unknown")
    else:
        result["data_size"], result["sequence"] = struct.unpack_from("<2I", core)
    count = result["data_size"]
    if count > len(core) - size:
        return None
    result["payload"] = binary_view(core[size:size + count])
    result["tail"] = binary_view(core[size + count:])
    return result


def assembled_stores(chunks: list[dict], limit: int = DEFAULT_LIMIT) -> list[dict]:
    result = []
    for index, chunk in enumerate(chunks):
        core = chunk["body"].get("core", {})
        if core.get("kind") != "dgn-store" or core["element_type"] != 39:
            continue
        count = core["component_count"]
        parts = [binary_bytes(core["payload"])]
        sequences = [core["sequence"]]
        diagnostic = ""
        if count > len(chunks) - index - 1 or core["total_size"] > limit:
            diagnostic = "DgnStore count/size exceeds available components or limit"
        else:
            for child in chunks[index + 1:index + 1 + count]:
                component = child["body"].get("core", {})
                if component.get("kind") != "dgn-store" or component.get("element_type") != 38:
                    diagnostic = "DgnStore component sequence is interrupted"
                    break
                sequences.append(component["sequence"])
                parts.append(binary_bytes(component["payload"]))
        if not diagnostic and (sequences != list(range(len(sequences))) or sum(map(len, parts)) != core["total_size"]):
            diagnostic = "DgnStore sequence/total size mismatch"
        payload = b"" if diagnostic else b"".join(parts)
        checksum_valid = not diagnostic and dgn_store_checksum(payload) == core["checksum"]
        if not diagnostic and not checksum_valid:
            diagnostic = "DgnStore checksum mismatch"
        item = {"chunk_index": index, "store_role": core["store_role"], "complete": not diagnostic,
                "checksum_verified": False, "application_id": core["application_id"]}
        if diagnostic:
            item["diagnostic"] = diagnostic
        else:
            item["checksum_verified"] = True
            item["payload"] = attribute_payload_view(payload, limit) if core["store_role"] == "XMLf" else binary_view(payload)
        result.append(item)
    return result


def dgn_store_checksum(data: bytes) -> int:
    checksum = 0
    for index, byte in enumerate(data):
        checksum ^= byte << ((index % 4) * 8)
    return checksum


def model_index_view(data: bytes, limit: int = DEFAULT_LIMIT) -> dict | None:
    if len(data) < 16:
        return None
    cookie, version, count, extra = struct.unpack_from("<4I", data)
    if cookie != 0xAA00BA11:
        return None
    cursor = BinaryCursor(data, limit)
    cursor.offset = 16
    result = {"kind": "dgn-model-index", "cookie": cookie, "version": version,
              "item_count": count, "original": binary_view(data), "items": []}
    if version != 2:
        result["diagnostic"] = "Unsupported model index version; bytes preserved"
        return result
    try:
        result["extra_header"] = binary_view(cursor.take(extra))
        if count > (len(data) - cursor.offset) // 32:
            raise ValueError("Model index count exceeds available records")
        for index in range(count):
            raw = cursor.take(32)
            model_type, flags, model_id, saved, total, name_size, description_size, unused, mask_size, cell_type = struct.unpack_from("<2HId6H", raw)
            if total < 32 or name_size % 2 or description_size % 2 or name_size + description_size + mask_size > total - 32 or not math.isfinite(saved):
                raise ValueError("Invalid model index item extent")
            body = BinaryCursor(cursor.take(total - 32), limit)
            item = {"model_type": model_type, "flags": flags, "model_id": model_id,
                    "last_saved": saved, "cell_type": cell_type,
                    "name": body.take(name_size).decode("utf-16-le"),
                    "description": body.take(description_size).decode("utf-16-le"),
                    "level_mask": binary_view(body.take(mask_size))}
            item["extension"] = binary_view(body.data[body.offset:])
            result["items"].append(item)
        if cursor.offset != len(data):
            raise ValueError("Unexpected model index trailing bytes")
    except (ValueError, UnicodeError, struct.error) as error:
        result["diagnostic"] = str(error)
        result["complete"] = False
        return result
    result["complete"] = True
    return result


def model_header_view(data: bytes) -> dict | None:
    if len(data) < 4096:
        return None
    count, major, minor = struct.unpack_from("<3I", data)
    return {"kind": "dgn-model-header", "num_pointer_blocks": count,
            "major_version": major, "minor_version": minor,
            "reserved": binary_view(data[12:4096]), "model_element": binary_view(data[4096:]),
            "original": binary_view(data)}


def design_header_view(data: bytes) -> dict | None:
    if len(data) < 1576:
        return None
    return {"kind": "dgn-design-header", "design_header": binary_view(data[:1576]),
            "extension": binary_view(data[1576:]), "original": binary_view(data)}


def manifest_view(data: bytes) -> dict:
    return {"kind": "dgn-manifest", "original": binary_view(data),
            "note": "File identity/provenance is retained without issuing new identities"}


def stream_role(names: list[str]) -> str:
    if names == ["Dgn~H"]:
        return "File/design header"
    if names == ["Dgn~Mf"]:
        return "File identity manifest"
    if names == ["Dgn^Ix", "Dgn~Mix"]:
        return "Model/cell index"
    if names[-1] == "Dgn~Mh":
        return "Model header"
    if names[-1] == "Dgn~S":
        return "Volatile session data"
    if names[-1] in ("Dgn~Fprov", "Dgn~Mprov"):
        return "Provenance"
    if names[0] in (".Embedded", ".EmbeddedFonts"):
        return "Passive embedded content"
    if names[0] in ("Dgn~Pr", "Dgn~ULC", "Dgn~RLC", "Dgn~RMC", "Dgn~SKY"):
        return "Protected content"
    return "Unknown" if len(names) < 2 or not names[-1].startswith("$") else "Attribute block" if names[-2].endswith("A") else "Element block"


def native_core_view(core: bytes, element_type: int) -> dict | None:
    if element_type not in ELEMENT_TYPES:
        return None
    result = {"kind": "dgn-native-core", "element_type": element_type,
              "type_name": ELEMENT_TYPES[element_type], "original": binary_view(core)}
    if element_type in (18, 19, 24, 27, 34, 92, 93, 97, 98, 105) and len(core) >= 4:
        result["component_count"] = struct.unpack_from("<I", core)[0]
    if element_type == 105 and len(core) >= 8:
        result["mesh_style"] = struct.unpack_from("<I", core, 4)[0]
    if element_type == 22 and len(core) >= 8:
        result["point_count"] = struct.unpack_from("<I", core)[0]
        result["note"] = "Point coordinates and per-point rotations require dimensionality-specific interpretation"
    if element_type == 23 and len(core) >= 104:
        result["cone_flags"] = struct.unpack_from("<H", core)[0]
        result["orientation"] = list(struct.unpack_from("<4d", core, 8))
        result["center_1"] = list(struct.unpack_from("<3d", core, 40))
        result["radius_1"] = struct.unpack_from("<d", core, 64)[0]
        result["center_2"] = list(struct.unpack_from("<3d", core, 72))
        result["radius_2"] = struct.unpack_from("<d", core, 96)[0]
    if element_type == 24 and len(core) >= 40:
        result.update(zip(("flags", "poles_u", "knots_u", "rules_u", "surface_flags",
                           "poles_v", "knots_v", "rules_v", "boundary_count"), struct.unpack_from("<9I", core, 4)))
    if element_type == 27 and len(core) >= 16:
        result["flags"], result["pole_count"], result["knot_count"] = struct.unpack_from("<3I", core, 4)
    if element_type == 25 and len(core) >= 8:
        number, count = struct.unpack_from("<2I", core)
        if count <= (len(core) - 8) // 16:
            result["boundary_number"] = number
            result["uv_points"] = [list(struct.unpack_from("<2d", core, 8 + index * 16)) for index in range(count)]
    if element_type == 34 and len(core) >= 128:
        result["version"], result["anonymous"], result["class"] = struct.unpack_from("<2BH", core, 4)
        result["range_diagonal"] = list(struct.unpack_from("<3d", core, 8))
        result["rotation_scale"] = list(struct.unpack_from("<9d", core, 32))
        result["origin"] = list(struct.unpack_from("<3d", core, 104))
    if element_type in (26, 28) and len(core) % 8 == 0:
        values = list(struct.unpack("<" + "d" * (len(core) // 8), core))
        if all(math.isfinite(value) for value in values):
            result["values"] = values
    pending = list(result.values())
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, float) and not math.isfinite(value):
            return {"kind": "dgn-native-core", "element_type": element_type,
                    "type_name": ELEMENT_TYPES[element_type], "original": binary_view(core),
                    "diagnostic": "Non-finite native scalar; payload retained without typed values"}
    return result


def gcs_view(core: bytes) -> dict | None:
    if len(core) < 12 or struct.unpack_from("<H", core)[0] != 182:
        return None
    subsignature = struct.unpack_from("<H", core, 2)[0]
    if subsignature not in (0x1000, 0x2000):
        return None
    size, version = struct.unpack_from("<2i", core, 4)
    result = {"kind": "dgn-gcs", "signature": 182, "subsignature": subsignature,
              "declared_size": size, "version": version, "original": binary_view(core)}
    if len(core) < 860:
        result["diagnostic"] = "Truncated legacy GCS base; remaining bytes preserved"
        return result
    result["minor_version"] = struct.unpack_from("<i", core, 4 + 580)[0]
    if (version, result["minor_version"]) not in ((2, 4000), (3, 0)):
        result["diagnostic"] = "Unsupported legacy GCS version"
        return result
    for name, offset, length in (("coordinate_system", 144, 24), ("projection", 216, 24),
                                 ("datum", 304, 64), ("ellipsoid", 368, 64),
                                 ("description", 432, 64), ("source", 496, 64),
                                 ("unit_name", 560, 16), ("grid_file", 702, 76)):
        raw = core[4 + offset:4 + offset + length].split(b"\0", 1)[0]
        result[name] = raw.decode("ascii") if raw.isascii() else binary_view(raw)
    result["vertical_datum"], marker = struct.unpack_from("<2H", core, 4 + 592)
    result["vertical_datum_valid"] = marker == 0x8117
    result["epsg"] = struct.unpack_from("<H", core, 4 + 696)[0]
    result["transform_parameters"] = list(struct.unpack_from("<12d", core, 4 + 600))
    if not all(math.isfinite(value) for value in result["transform_parameters"]):
        del result["transform_parameters"]
        result["diagnostic"] = "Non-finite GCS transform; parameters remain opaque"
    return result


def tag_view(core: bytes) -> dict | None:
    if len(core) < 192:
        return None
    version, flags = struct.unpack_from("<2H", core, 24)
    definition, data_type = struct.unpack_from("<2H", core, 80)
    size, new_size, codepage = struct.unpack_from("<2Hi", core, 184)
    if version != 3 or size > len(core) - 192:
        return None
    result = {"kind": "dgn-tag", "version": version, "flags": flags,
              "definition_id": definition, "data_type": data_type, "codepage": codepage,
              "data_size": size, "extended_data_size": new_size,
              "options_count": core[179], "original": binary_view(core)}
    raw = core[192:192 + size]
    formats = {2: "h", 3: "i", 4: "d"}
    if data_type in formats and size == struct.calcsize("<" + formats[data_type]):
        number = struct.unpack("<" + formats[data_type], raw)[0]
        if not isinstance(number, float) or math.isfinite(number):
            result["value"] = number
    elif data_type == 1 and raw.endswith(b"\0") and raw[:-1].isascii() and b"\0" not in raw[:-1] and codepage in (-1, 0, 1252, 65001):
        result["value"] = raw[:-1].decode("ascii")
        result["encoding"] = "ascii"
    return result


def tag_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    old = tag_view(original)
    if old is None:
        raise ValueError("Invalid tag snapshot")
    for key in old:
        if key not in ("value", "original") and view[key] != old[key]:
            raise ValueError("Tag identity, encoding and metadata are read-only")
    if view.get("value") == old.get("value"):
        return original
    if "value" not in old or old["options_count"] or old["extended_data_size"]:
        raise ValueError("Unsupported tag options or extended value")
    data_type = old["data_type"]
    if data_type == 1:
        if "\0" in view["value"]:
            raise ValueError("Tag string cannot contain NUL")
        value = view["value"].encode("ascii") + b"\0"
    else:
        if type(view["value"]) not in (int, float) or not math.isfinite(view["value"]):
            raise ValueError("Invalid tag scalar")
        value = struct.pack("<" + {2: "h", 3: "i", 4: "d"}[data_type], view["value"])
    tail = original[192 + old["data_size"]:]
    if len(value) != old["data_size"] and any(tail):
        raise ValueError("Cannot resize tag with unknown extension bytes")
    if len(value) == old["data_size"]:
        return original[:192] + value + tail
    result = bytearray(original[:192])
    struct.pack_into("<H", result, 184, len(value))
    result.extend(value)
    result.extend(b"\0" * (-len(result) % 2))
    return bytes(result)


def record_core_view(core: bytes, element_type: int, level: int, graphics: bool) -> dict | None:
    typed = table_record_view(core, element_type, level) or matrix_view(core, element_type) or dgn_store_view(core, element_type)
    if typed:
        return typed
    if element_type == 37 and graphics:
        tag = tag_view(core)
        if tag:
            return tag
    if element_type == 66 and not graphics:
        gcs = gcs_view(core)
        if gcs:
            return gcs
    layout = RECORD_LAYOUTS.get(element_type)
    if layout and len(core) >= max(offset + struct.calcsize("<" + format) for offset, format, readonly in layout.values()):
        fields = {}
        for name, (offset, format, readonly) in layout.items():
            values = struct.unpack_from("<" + format, core, offset)
            fields[name] = values[0] if len(values) == 1 else list(values)
        if not finite_numbers(fields):
            return None
        return {"kind": "dgn-fixed-record", "element_type": element_type, "fields": fields, "original": binary_view(core)}
    if element_type == 66 and level == 20 and not graphics and len(core) >= 2:
        return {"kind": "dgn-application-data", "signature_word": struct.unpack_from("<H", core)[0], "payload": binary_view(core[2:])}
    if element_type == 66 and level == 10 and graphics and len(core) >= 476:
        command = core[:256].split(b"\0", 1)[0]
        if command.isascii():
            return {"kind": "dgn-startup-command", "command": command.decode("ascii"), "original": binary_view(core), "warning": "Passive edit only. The DGN application can execute startup data when opening a file. Use an isolated test environment."}
    return native_core_view(core, element_type)


def record_core_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    result = bytearray(original)
    if view["kind"] == "dgn-startup-command":
        encoded = view["command"].encode("ascii")
        if b"\0" in encoded or len(encoded) > 255:
            raise ValueError("Startup command must be NUL-free ASCII, at most 255 bytes")
        if encoded == original[:256].split(b"\0", 1)[0]:
            return original
        result[:256] = encoded + b"\0" * (256 - len(encoded))
        return bytes(result)
    layout = RECORD_LAYOUTS[view["element_type"]]
    for name, (offset, format, readonly) in layout.items():
        previous = struct.unpack_from("<" + format, original, offset)
        value = view["fields"][name]
        values = tuple(value) if isinstance(value, list) else (value,)
        if readonly and values != previous:
            raise ValueError(f"Record {name} is read-only; dependent metadata is not repaired")
        struct.pack_into("<" + format, result, offset, *values)
    return bytes(result)


def generic_element_view(body: bytes, element_type: int, flags: int) -> dict | None:
    header_size = 96 if flags & 0x1000 else 24
    if len(body) < header_size:
        return None
    attr_offset = struct.unpack_from("<I", body)[0] * 2 - 8
    if not header_size <= attr_offset <= len(body):
        return None
    if not math.isfinite(struct.unpack_from("<d", body, 16)[0]):
        return None
    result = {"kind": "dgn-element", "element_type": element_type, "element_id": struct.unpack_from("<Q", body, 8)[0], "level_id": struct.unpack_from("<I", body, 4)[0], "last_modified": struct.unpack_from("<d", body, 16)[0], "original": binary_view(body), "core": binary_view(body[header_size:attr_offset]), "linkages": linkages_view(body[attr_offset:]), "edit_warning": "Raw core/linkage edits are advanced mutations. IDs and dimensionality are read-only; ranges, parent layouts, dependencies and cross-stream indexes are not repaired. External targets are never opened."}
    result["type_name"] = ELEMENT_TYPES.get(element_type, "Unknown")
    result["core"] = record_core_view(body[header_size:attr_offset], element_type, result["level_id"], bool(flags & 0x1000)) or result["core"]
    if result["core"].get("kind") == "dgn-gcs":
        result["type_name"] = "Geographic coordinate system"
    if flags & 0x1000:
        properties = struct.unpack_from("<H", body, 32)[0]
        result["display"] = {"graphics_group": struct.unpack_from("<I", body, 24)[0], "priority": struct.unpack_from("<i", body, 28)[0], "properties_flags": properties, "is_3d": bool(properties & 0x800), "invisible": bool(properties & 0x80)}
        style, weight, color = struct.unpack_from("<i2I", body, 36)
        result["display"].update({"line_style": style, "line_weight": weight, "color": color})
        result["display"]["scan_range"] = list(struct.unpack_from("<6q", body, 48))
        result["core"] = geometry_view(body[header_size:attr_offset], element_type, bool(properties & 0x800)) or result["core"]
    return result


def generic_element_bytes(view: dict) -> bytes:
    original = binary_bytes(view["original"])
    result = bytearray(original)
    if view["element_id"] != struct.unpack_from("<Q", original, 8)[0]:
        raise ValueError("Element IDs are read-only because other records reference them")
    struct.pack_into("<I", result, 4, view["level_id"])
    struct.pack_into("<d", result, 16, view["last_modified"])
    header_size = 24
    if "display" in view:
        header_size = 96
        display = view["display"]
        properties = display["properties_flags"]
        old_properties = struct.unpack_from("<H", original, 32)[0]
        if properties & 0x800 != old_properties & 0x800 or display["is_3d"] != bool(old_properties & 0x800):
            raise ValueError("Changing element dimensionality requires the DGN application")
        properties = (properties & ~0x80) | (0x80 if display["invisible"] else 0)
        struct.pack_into("<IiH", result, 24, display["graphics_group"], display["priority"], properties)
        struct.pack_into("<i2I", result, 36, display["line_style"], display["line_weight"], display["color"])
        struct.pack_into("<6q", result, 48, *display["scan_range"])
    core = view_bytes(view["core"])
    linkages = view_bytes(view["linkages"])
    if len(core) % 2 or len(linkages) % 2:
        raise ValueError("DGN core/linkage data must have even byte lengths")
    result = result[:header_size] + core + linkages
    struct.pack_into("<I", result, 0, (header_size + len(core) + 8) // 2)
    return bytes(result)


def element_chunks_view(data: bytes) -> dict | None:
    chunks = []
    position = 0
    while position < len(data):
        if position + 12 > len(data):
            return None
        signature, element_type, flags, words = struct.unpack_from("<I2HI", data, position)
        end = position + 4 + words * 2
        if words < 4 or end > len(data):
            return None
        body = data[position + 12:end]
        parsed = (text_element_view(body, element_type, flags) or generic_element_view(body, element_type, flags)) if signature == 0 else None
        chunks.append({"signature": signature, "element_type": element_type, "element_flags": flags, "body": parsed or binary_view(body)})
        position = end
    for assembly in assembled_stores(chunks):
        chunks[assembly["chunk_index"]]["body"]["store_assembly"] = assembly
    return {"kind": "dgn-element-chunks", "chunks": chunks}


class FolderStore:
    """Writes extracted workspace files below a confined folder."""

    def __init__(self, folder: Path, cancel=None):
        self.folder = folder
        self.cancel = cancel

    def directory(self, relative: str) -> None:
        inside(self.folder, relative).mkdir(parents=True, exist_ok=True)

    def data(self, relative: str, data: bytes) -> None:
        checkpoint(self.cancel)
        path = inside(self.folder, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def view(self, relative: str, view: dict, bytes_mode: str = "hex") -> None:
        checkpoint(self.cancel)
        write_view(inside(self.folder, relative), view, bytes_mode)

    def read(self, relative: str, limit: int) -> bytes:
        return read_limited(inside(self.folder, relative), limit)

    def exists(self, relative: str) -> bool:
        return inside(self.folder, relative).exists()


class MemoryStore:
    """Keeps the same extracted workspace files in memory for passive baselines and snapshots."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files: dict[str, bytes] = dict(files or {})
        self.directories: set[str] = set()

    def directory(self, relative: str) -> None:
        self.check(relative)
        self.directories.add(relative)

    def data(self, relative: str, data: bytes) -> None:
        self.check(relative)
        self.files[relative] = bytes(data)

    @staticmethod
    def check(relative: str) -> None:
        candidate = Path(relative)
        if not relative or relative.startswith(("/", "\\")) or candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
            raise ValueError(f"Unsafe workspace path: {relative!r}")

    def view(self, relative: str, view: dict, bytes_mode: str = "hex") -> None:
        if bytes_mode == "escaped":
            view = readable_bytes(view)
        self.data(relative, (json.dumps(view, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))

    def read(self, relative: str, limit: int) -> bytes:
        self.check(relative)
        if relative not in self.files:
            raise FileNotFoundError(f"Workspace file is missing: {relative!r}")
        if len(self.files[relative]) > limit:
            raise ValueError(f"File exceeds --max-mib: {relative}")
        return self.files[relative]

    def exists(self, relative: str) -> bool:
        self.check(relative)
        return relative in self.files


def file_store(folder: Path | FolderStore | MemoryStore) -> FolderStore | MemoryStore:
    return folder if isinstance(folder, (FolderStore, MemoryStore)) else FolderStore(folder)


def externalize_text(folder: Path | FolderStore | MemoryStore, relative: str, view: dict) -> None:
    store = file_store(folder)
    counter = 0

    def visit(node):
        nonlocal counter
        if isinstance(node, dict):
            if node.get("kind") in ("text", "xml", "json-text") and "text" in node:
                counter += 1
                extension = {"xml": "xml", "json-text": "json", "text": "txt"}[node["kind"]]
                label = "-" + disk_name(ET.fromstring(node["text"]).tag.split("}")[-1]) if node["kind"] == "xml" else ""
                filename = f"content/{relative}/{counter:04d}{label}.{extension}"
                store.data(filename, node.pop("text").encode("utf-8"))
                node["text_file"] = filename
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(view)


def hydrate_text(folder: Path | FolderStore | MemoryStore, view: dict, limit: int) -> None:
    store = file_store(folder)
    if isinstance(view, dict):
        if view.get("kind") == "object-reference":
            view["payload"] = json.loads(store.read(view["file"], limit).decode("utf-8"))
            if view["payload"].get("kind") not in ("dgn-text-element", "dgn-text-node", "dgn-text-field", "dgn-element", "dgn-xattribute"):
                raise ValueError("Object reference resolves to an unsupported object kind")
        if "text_file" in view:
            if "text" in view:
                raise ValueError("Use text_file or inline text, not both")
            view["text"] = store.read(view["text_file"], limit).decode("utf-8")
        for value in view.values():
            hydrate_text(store, value, limit)
    elif isinstance(view, list):
        for value in view:
            hydrate_text(store, value, limit)


def export_objects(folder: Path | FolderStore | MemoryStore, relative: str, names: list[str], view: dict, index: list[dict], bytes_mode: str = "hex") -> None:
    store = file_store(folder)
    if view["kind"] == "dgn-element-chunks":
        for position, chunk in enumerate(view["chunks"]):
            body = chunk["body"]
            if body["kind"] == "dgn-element" and names[0] not in ("Dgn-Md", "Dgn-Nd"):
                index.append({"kind": body["kind"], "element_type": chunk["element_type"], "element_id": body["element_id"], "file": "data/" + relative + ".json", "inline": True, "ole_path": names, "chunk_index": position})
                continue
            if body["kind"] in ("dgn-text-element", "dgn-text-node", "dgn-element"):
                filename = f"objects/{relative}/{position:05d}-element-{body['element_id']}.json"
                store.view(filename, body, bytes_mode)
                item = {"kind": body["kind"], "element_id": body["element_id"], "file": filename, "ole_path": names, "chunk_index": position}
                item["element_type"] = chunk["element_type"]
                item["type_name"] = ELEMENT_TYPES.get(chunk["element_type"], "Unknown")
                if body["kind"] == "dgn-text-element":
                    item["text_preview"] = body["string"].get("text")
                    item["encoding"] = body["string"].get("mode", "opaque-font-codes")
                index.append(item)
                chunk["body"] = {"kind": "object-reference", "file": filename}
            if chunk["element_type"] == 66:
                raw = view_bytes(body)
                if len(raw) >= 24:
                    level = struct.unpack_from("<I", raw, 4)[0]
                    if 10 <= level <= 19:
                        providers = {10: "XBase", 11: "Informix", 12: "RIS", 13: "Oracle", 14: "Ingres", 15: "Sybase", 16: "ODBC", 17: "Continuum Oracle", 18: "OLE DB", 19: "Bentley Universal Database"}
                        index.append({"kind": "database-connection-record", "provider": providers[level], "element_id": struct.unpack_from("<Q", raw, 8)[0], "ole_path": names, "chunk_index": position, "editable": False, "note": "Source-defined type/level. Connection payload remains opaque; no connection is opened."})
    elif view["kind"] == "dgn-attribute-sets":
        for group in view["sets"]:
            for attribute in group["attributes"]:
                original_payload = attribute["payload"]
                if attribute["payload"]["kind"] == "dgn-text-field":
                    field = attribute["payload"]
                    filename = f"fields/{relative}/element-{group['element_id']}-attribute-{attribute['attribute_id']}.json"
                    store.view(filename, field, bytes_mode)
                    index.append({"kind": "dgn-text-field", "element_id": group["element_id"], "attribute_id": attribute["attribute_id"], "file": filename, "ole_path": names, "field_type": field["field_type"], "placeholder_link_type": field["placeholder_link_type"], "property": field["dictionary"].get("Access"), "display_label": field["dictionary"].get("DisplayValue")})
                    attribute["payload"] = {"kind": "object-reference", "file": filename}
                else:
                    identity = {"element_id": group["element_id"], "handler_id": attribute["handler_id"], "attribute_id": attribute["attribute_id"]}
                    filename = f"attributes/{relative}/element-{group['element_id']}-handler-{attribute['handler_id']:08x}-attribute-{attribute['attribute_id']}.json"
                    wrapped = {"kind": "dgn-xattribute", "identity": identity, "original_identity": dict(identity), "payload": attribute["payload"], "edit_warning": "Identity is read-only. XML/text or raw payload is editable; application-specific constraints and related attributes are not repaired."}
                    store.view(filename, wrapped, bytes_mode)
                    index.append({"kind": "dgn-xattribute", **identity, "file": filename, "ole_path": names, "payload_kind": attribute["payload"]["kind"]})
                    attribute["payload"] = {"kind": "object-reference", "file": filename}
                if attribute["handler_id"] & 0xFFFF == 22261 or attribute["handler_id"] >> 16 == 22261:
                    payload = original_payload
                    while payload.get("kind") in ("compressed-xattribute", "terminated-text"):
                        payload = payload["payload"]
                    index.append({"kind": "design-link-attribute", "element_id": group["element_id"], "attribute_id": attribute["attribute_id"], "ole_path": names, "file": payload.get("text_file"), "note": "Stored link metadata only. External targets are not followed."})


def view_bytes(view: dict) -> bytes:
    if view["kind"] == "dgn-xml-fragment":
        return xml_fragment_bytes(view)
    if view["kind"] in ("dgn-table-header", "dgn-table-entry"):
        return table_record_bytes(view)
    if view["kind"] == "dgn-xdata":
        return xdata_bytes(view)
    if view["kind"] == "dgn-tag":
        return tag_bytes(view)
    if view["kind"] == "dgn-symbology":
        return symbology_bytes(view)
    if view["kind"] == "dgn-xml-linkage":
        original = binary_bytes(view["original"])
        old = linkage_payload_view(original, 22243)
        for key in ("linkage_type", "application_id", "application_type", "reserved", "tail"):
            if readable_bytes(view[key]) != readable_bytes(old[key]):
                raise ValueError("XML linkage identities and extensions are read-only")
        payload = view_bytes(view["payload"])
        if payload == view_bytes(old["payload"]):
            return original
        tail = binary_bytes(view["tail"])
        if len(payload) != struct.unpack_from("<I", original, 8)[0] and any(tail):
            raise ValueError("Cannot resize XML linkage with unknown extension bytes")
        result = original[:8] + struct.pack("<I", len(payload)) + payload + tail
        return result + b"\0" * (-len(result) % 2)
    if view["kind"] in PASSIVE_KINDS and "original" in view:
        decoders = {
            "dgn-design-header": design_header_view, "dgn-manifest": manifest_view,
            "dgn-model-index": model_index_view, "dgn-model-header": model_header_view,
            "dgn-becxml": becxml_view, "dgn-ecxd": ecxd_view, "dgn-tflabel": tflabel_view,
            "dgn-ecx-instance": lambda data: ecx_instance_view(data, view["handler_id"]),
            "dgn-gcs": gcs_view,
            "dgn-matrix": lambda data: matrix_view(data, view["element_type"]),
            "dgn-store": lambda data: dgn_store_view(data, view["element_type"]),
            "dgn-native-core": lambda data: native_core_view(data, view["element_type"]),
            "dgn-dependency": lambda data: linkage_payload_view(data, 22224),
            "dgn-bitmask": lambda data: linkage_payload_view(data, 22227),
            "dgn-multistate-mask": lambda data: linkage_payload_view(data, 22288),
            "dgn-symbology": lambda data: linkage_payload_view(data, 22241),
        }
        return passive_bytes(view, decoders[view["kind"]])
    if view["kind"] in ("dgn-fixed-record", "dgn-startup-command"):
        return record_core_bytes(view)
    if view["kind"] == "dgn-application-data":
        return struct.pack("<H", view["signature_word"]) + view_bytes(view["payload"])
    if view["kind"] == "dgn-xattribute":
        if view["identity"] != view["original_identity"]:
            raise ValueError("XAttribute identity is read-only")
        return view_bytes(view["payload"])
    if view["kind"] == "dgn-linkages":
        return b"".join(linkage_bytes(record) for record in view["records"])
    if view["kind"] == "dgn-linkage":
        return linkage_bytes(view)
    if view["kind"] == "dgn-string-linkage":
        return string_linkage_bytes(view)
    if view["kind"] == "dgn-geometry":
        return geometry_bytes(view)
    if view["kind"] == "dgn-element":
        return generic_element_bytes(view)
    if view["kind"] == "dgn-text-field":
        return text_field_bytes(view)
    if view["kind"] == "object-reference":
        return view_bytes(view["payload"])
    if view["kind"] in ("dgn-text-element", "dgn-text-node"):
        return text_element_bytes(view)
    if view["kind"] == "dgn-varichar":
        text = view["text"]
        if "\0" in text:
            raise ValueError("DGN text cannot contain embedded NUL characters")
        if view["mode"] == "ascii-font-codes":
            if any(not 32 <= ord(char) < 127 for char in text):
                raise ValueError("Locale/font-specific text edits must stay within printable ASCII")
            return text.encode("ascii")
        if view["mode"] == "unicode-narrow" and all(ord(char) <= 255 for char in text):
            return b"\xff\xfe\x01\x00" + text.encode("latin-1")
        if view["mode"] in ("unicode-narrow", "unicode-wide"):
            if text.startswith("\x01"):
                raise ValueError("Unicode VariChar cannot start with U+0001")
            return b"\xff\xfe" + text.encode("utf-16-le")
        raise ValueError("Unsupported VariChar text mode")
    if view["kind"] == "dgn-element-chunks":
        output = bytearray()
        for chunk in view["chunks"]:
            body = view_bytes(chunk["body"])
            if len(body) % 2:
                raise ValueError("DGN element chunk bodies must have an even byte length")
            output.extend(struct.pack("<I2HI", chunk["signature"], chunk["element_type"], chunk["element_flags"], (len(body) + 8) // 2))
            output.extend(body)
        return bytes(output)
    if view["kind"] == "dgn-model-header":
        return struct.pack("<3I", view["num_pointer_blocks"], view["major_version"], view["minor_version"]) + view_bytes(view["remaining"])
    if view["kind"] == "ole-properties":
        return properties_bytes(view)
    if view["kind"] == "ole-property-value":
        original = binary_bytes(view["original"])
        old = property_value(original, view["codepage"])
        fields = {key: view[key] for key in ("variant_type", "value", "encoding") if key in view}
        if old == fields:
            return original
        variant = view["variant_type"]
        if variant in (30, 31):
            terminator = b"\0\0" if variant == 31 or view["encoding"] == "utf-16-le" else b"\0"
            value = view["value"].encode(view["encoding"]) + terminator
            count = len(value) // 2 if variant == 31 else len(value)
            encoded = struct.pack("<2I", variant, count) + value
        else:
            formats = {2: "h", 3: "i", 4: "f", 5: "d", 11: "h", 16: "b", 17: "B", 18: "H", 19: "I", 20: "q", 21: "Q", 64: "Q"}
            value = (-1 if view["value"] else 0) if variant == 11 else view["value"]
            encoded = struct.pack("<I" + formats[variant], variant, value)
        return encoded + b"\0" * (-len(encoded) % 4)
    if view["kind"] == "dgn-attribute-sets":
        output = bytearray()
        for attr_set in view["sets"]:
            records = bytearray()
            for attribute in attr_set["attributes"]:
                data = view_bytes(attribute["payload"])
                size_flags = len(data) | (0x80000000 if attribute["archive"] else 0)
                records.extend(struct.pack("<4I", attribute["handler_id"], attribute["attribute_id"], size_flags, attribute["reserved"]))
                records.extend(data)
            records.extend(struct.pack("<I", attr_set["flags"]))
            output.extend(struct.pack("<4IQI", attr_set["signature"], len(records), attr_set["set_type"], attr_set["reserved"], attr_set["element_id"], len(attr_set["attributes"])))
            output.extend(records)
        return bytes(output)
    if view["kind"] == "terminated-text":
        return view_bytes(view["payload"]) + bytes.fromhex(view["terminator_hex"])
    if view["kind"] == "compressed-xattribute":
        payload = view_bytes(view["payload"])
        compression = view["compression_type"]
        if compression not in (1, 2, 3):
            raise ValueError("Unsupported XAttribute compression type")
        original = binary_bytes(view["original"])
        original_type, original_padding, original_size = struct.unpack_from("<2HI", original)
        decoded = inflate(original[8:], max(original_size, len(payload))) if original_type == 3 else (original[8:], b"")
        if decoded is not None and not decoded[1] and (payload, compression, view["padding"]) == (decoded[0], original_type, original_padding):
            return original
        encoded = zlib.compress(payload) if compression == 3 else payload
        return struct.pack("<2HI", compression, view["padding"], len(payload)) + encoded
    if view["kind"] in ("text", "xml", "json-text"):
        if view["kind"] == "xml":
            ET.fromstring(view["text"])
        elif view["kind"] == "json-text":
            json.loads(view["text"])
        return bytes.fromhex(view.get("bom_hex", "")) + view["text"].encode(view["encoding"])
    if view["kind"] == "dgn-block-header":
        return struct.pack("<4I", view["num_entries"], view["flags"], *view["reserved"])
    if view["kind"] == "dgn-file-header":
        return struct.pack("<2H4I", view["flags"], view["compression_level"], *view["encryption_data"])
    if view["kind"] == "uint32":
        return struct.pack("<I", view["value"])
    if view["kind"] not in ("opaque-bytes", "byte-string"):
        raise ValueError(f"Unsupported editable representation: {view['kind']!r}")
    return binary_bytes(view)


def write_view(path: Path, view: dict, bytes_mode: str = "hex") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if bytes_mode == "escaped":
        view = readable_bytes(view)
    path.write_text(json.dumps(view, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def read_view(folder: Path | FolderStore | MemoryStore, relative: str, representation: str | None, limit: int, counts: dict | None = None) -> bytes:
    store = file_store(folder)
    data = store.read(relative, limit)
    if representation == "json-view":
        view = json.loads(data.decode("utf-8"))
        hydrate_text(store, view, limit)
        if counts is not None and view["kind"] == "dgn-attribute-sets":
            counts["num_entries"] = len(view["sets"])
        data = view_bytes(view)
    if len(data) > limit:
        raise ValueError("Encoded editable representation exceeds --max-mib")
    return data


def inspect_dgn(source: Path, limit: int) -> dict:
    types = Counter()
    model_types = Counter()
    handlers = Counter()
    keys = Counter()
    link_ids = Counter()
    tables = Counter()
    models = set()
    unparsed = []
    with ole_reader().OleFileIO(str(source)) as ole:
        if not ole.exists("Dgn~H"):
            raise ValueError("Not a supported DGN V8 file")
        header = ole.openstream("Dgn~H").read(20)
        if len(header) < 20 or struct.unpack_from("<H", header)[0] & 2:
            raise ValueError("Encrypted/truncated DGN header is unsupported")
        names_list = ole.listdir()
        for names in names_list:
            if ole.get_size(names) > limit:
                raise ValueError(f"Stream exceeds --max-mib: {names!r}")
            if len(names) > 1 and names[0] in ("Dgn-Md", "Dgn-Nd"):
                models.add(names[1])
            codec, payload, prefix, suffix = decode_stream(names, ole.openstream(names).read(), limit)
            if not names[-1].startswith("$") or len(prefix) != 16:
                continue
            attributes = len(names) > 1 and names[-2].endswith("A")
            view = attribute_sets_view(payload, limit) if attributes else element_chunks_view(payload)
            if view is None:
                unparsed.append(names)
            elif attributes:
                handlers.update(attribute["handler_id"] for group in view["sets"] for attribute in group["attributes"])
            else:
                for chunk in view["chunks"]:
                    if chunk["signature"] != 0:
                        continue
                    types[chunk["element_type"]] += 1
                    if names[0] in ("Dgn-Md", "Dgn-Nd"):
                        model_types[chunk["element_type"]] += 1
                    links = chunk["body"].get("linkages", {})
                    if links.get("kind") == "dgn-linkages":
                        link_ids.update(record["primary_id"] for record in links["records"])
                        keys.update(record["payload"]["key"] for record in links["records"] if record["payload"]["kind"] == "dgn-string-linkage")
                    core = chunk["body"].get("core", {})
                    if core.get("kind") in ("dgn-table-header", "dgn-table-entry"):
                        tables[(core["table_level"], chunk["element_type"])] += 1
    def entries(counts):
        return [{"type": number, "name": ELEMENT_TYPES.get(number, "Unknown"), "count": count} for number, count in sorted(counts.items())]
    return {"source": str(source), "sha256": file_digest(source), "model_count": len(models), "stream_count": len(names_list), "element_count": sum(types.values()), "element_types": entries(types), "model_element_types": entries(model_types),
            "metadata_tables": [{"level": level, "name": TABLE_LEVELS.get(level, "Unknown"), "element_type": element_type, "count": count} for (level, element_type), count in sorted(tables.items())],
            "linkage_ids": [{"primary_id": primary, "name": LINKAGE_NAMES.get(primary, "Unknown"), "count": count} for primary, count in sorted(link_ids.items())],
            "string_linkage_keys": [{"key": key, "name": STRING_LINKAGE_KEYS.get(key, "Unknown"), "count": count} for key, count in sorted(keys.items())],
            "attribute_handlers": [{"handler_id": f"0x{handler:08x}", "major": handler >> 16, "minor": handler & 0xFFFF, "count": count} for handler, count in sorted(handlers.items())],
            "unparsed_element_streams": unparsed, "warning": "Passive structural inventory, not proof of complete OpenBuildings feature coverage or rendering validity. External targets and active content are never opened."}


def editing_contract(view: dict, readonly: bool = False) -> dict:
    editable_fields = []
    read_only_fields = []
    informational = {"kind", "original", "original_identity", "edit_warning", "warning", "note", "description", "key_name", "type_name", "primary_name", "format_name", "schema_name", "store_assembly"}
    restricted = {
        "dgn-text-element": {"element_id", "is_3d", "enter_data_fields"},
        "dgn-text-node": {"element_id", "is_3d", "component_count"},
        "dgn-element": {"element_id", "element_type", "is_3d"},
        "dgn-geometry": {"element_type", "dimensions", "shape", "component_count"},
        "dgn-text-field": {"handler", "field_type", "formatter_name", "state_flags", "evaluation_flags", "matching_link_types", "compatible_link_types"},
        "dgn-string-linkage": {"key", "padding"},
        "dgn-xml-fragment": {"encoding_type", "schema_urn", "declared_stream_size", "declared_xml_data_size", "declared_schema_size", "declared_text_size", "tail"},
        "dgn-xml-linkage": {"linkage_type", "application_id", "application_type", "reserved", "tail"},
        "dgn-xattribute": {"identity"},
        "dgn-varichar": {"mode"},
        "byte-string": {"encoding", "bom_hex"},
        "text": {"encoding", "bom_hex"},
        "xml": {"encoding", "bom_hex"},
        "json-text": {"encoding", "bom_hex"},
        "terminated-text": {"terminator_hex"},
    }

    def visit(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            kind = node.get("kind")
            if kind in PASSIVE_KINDS:
                read_only_fields.append(pointer or "/")
                return
            if node.get("format_name") == "ECSchema":
                read_only_fields.append(pointer or "/")
                return
            if kind in ("dgn-table-header", "dgn-table-entry"):
                for key in node:
                    (editable_fields if key == "name" and node.get("table_level") == 2 else read_only_fields).append(pointer + "/" + key)
                return
            if kind == "dgn-tag":
                for key in node:
                    editable = key == "value" and not node["options_count"] and not node["extended_data_size"]
                    (editable_fields if editable else read_only_fields).append(pointer + "/" + key)
                return
            if kind == "dgn-symbology":
                for key in node:
                    (editable_fields if key == "weight" else read_only_fields).append(pointer + "/" + key)
                return
            if kind == "dgn-xdata":
                for index, item in enumerate(node["records"]):
                    for key in item:
                        path = pointer + f"/records/{index}/" + key
                        (editable_fields if key == "value" and item["group"] in (1000, 1040, 1041, 1042, 1070, 1071) else read_only_fields).append(path)
                read_only_fields.extend((pointer + "/tail", pointer + "/original", pointer + "/kind"))
                return
            if kind == "dgn-string-linkage" and node.get("key") == 62:
                read_only_fields.append(pointer or "/")
                return
            if kind in ("opaque-bytes", "byte-string") and not binary_bytes(node):
                read_only_fields.append(pointer or "/")
                return
            for key, value in node.items():
                path = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                if key == "editing":
                    continue
                if key in informational or key in restricted.get(kind, set()):
                    read_only_fields.append(path)
                elif kind == "dgn-fixed-record" and key == "element_type":
                    read_only_fields.append(path)
                elif kind == "dgn-fixed-record" and key == "fields":
                    for name, (offset, format, immutable) in RECORD_LAYOUTS[node["element_type"]].items():
                        (read_only_fields if immutable else editable_fields).append(path + "/" + name)
                elif kind == "dgn-text-field" and key == "dictionary":
                    for name in value:
                        (editable_fields if name == "DisplayValue" else read_only_fields).append(path + "/" + name.replace("~", "~0").replace("/", "~1"))
                else:
                    visit(value, path)
        elif isinstance(node, list) and node and any(isinstance(value, dict) for value in node):
            for index, value in enumerate(node):
                visit(value, pointer + "/" + str(index))
        else:
            editable_fields.append(pointer)

    if readonly:
        read_only_fields.append("/")
    else:
        visit(view, "")
    access = "rw" if editable_fields else "ro"
    return {"access": access, "editable_fields": editable_fields, "read_only_fields": read_only_fields, "note": "File-level access, not OS permissions. Only listed fields are supported edit inputs. Original snapshots are immutable. Raw bytes and framing are advanced; DGN application validation is still required."}


LABEL_ROOTS = {"data", "framing", "objects", "attributes", "fields", "content"}
LABEL_READONLY = {"objects/index.json", "field-choices.json", "object-choices.json"}


def label_candidate(relative: str) -> bool:
    path = PurePosixPath(relative)
    unmarked = str(path.with_name(path.stem.removesuffix(".ro").removesuffix(".rw") + path.suffix))
    return unmarked in {"manifest.json", *LABEL_READONLY} or relative.split("/")[0] in LABEL_ROOTS


def label_files(files: dict[str, bytes], manifest: dict, cancel=None, existing: set[str] | None = None) -> tuple[dict[str, bytes], dict[str, str]]:
    """Apply .ro/.rw access markers to workspace files in memory.

    Returns the labeled files (including manifest.rw.json and writable indexes) and
    the old-to-new name map. `manifest` is updated in place, as on disk.
    """
    existing = set(files) if existing is None else existing
    renames = {}
    schemas = {}
    readonly_paths = set()
    for relative in files:
        checkpoint(cancel)
        if not label_candidate(relative):
            continue
        path = PurePosixPath(relative)
        stem = path.stem.removesuffix(".ro").removesuffix(".rw")
        unmarked = str(path.with_name(stem + path.suffix))
        marker = "ro" if unmarked in LABEL_READONLY else "rw"
        if path.suffix == ".json" and not relative.startswith("content/"):
            schema = json.loads(files[relative].decode("utf-8"))
            if unmarked != "manifest.json":
                schema["editing"] = editing_contract(schema, unmarked in LABEL_READONLY)
                marker = schema["editing"]["access"]
            schemas[relative] = schema
        if marker == "ro":
            readonly_paths.add(relative)
        target = str(path.with_name(stem + "." + marker + path.suffix))
        if target != relative and target in existing:
            raise ValueError(f"Access-marker destination already exists: {target}")
        renames[relative] = target

    def references(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("file", "text_file", "prefix", "suffix", "objects_index", "field_choices", "object_choices") and isinstance(value, str) and value in renames:
                    node[key] = renames[value]
                else:
                    references(value)
        elif isinstance(node, list):
            for value in node:
                references(value)

    def serialized(view):
        return (json.dumps(view, indent=2, ensure_ascii=True) + "\n").encode("utf-8")

    labeled = {}
    for relative, target in renames.items():
        checkpoint(cancel)
        if relative in schemas:
            references(schemas[relative])
            labeled[target] = serialized(schemas[relative])
        else:
            labeled[target] = files[relative]
    references(manifest)
    manifest["writable_index"] = "writable-index.ro.json"
    manifest["writable_guide"] = "WRITABLE.ro.md"
    labeled["manifest.rw.json"] = serialized(manifest)
    objects = json.loads(labeled[manifest["objects_index"]].decode("utf-8"))["objects"] if "objects_index" in manifest else []
    inline_by_file = {}
    for obj in objects:
        if obj.get("inline"):
            inline_by_file.setdefault(obj["file"], []).append(f"/chunks/{obj['chunk_index']}/body")
    writable = []
    for relative, renamed in sorted(renames.items(), key=lambda item: item[1]):
        if relative in readonly_paths:
            continue
        category = relative.split("/")[0] if "/" in relative else "workspace"
        item = {"file": renamed, "category": category, "access": "rw", "edit_scope": "advanced stream/framing edits" if category in ("data", "framing", "workspace") else "supported object/content edits; read-only fields and edit_warning still apply"}
        if relative in schemas and "editing" in schemas[relative]:
            item["editable_fields"] = schemas[relative]["editing"]["editable_fields"]
            item["read_only_fields"] = schemas[relative]["editing"]["read_only_fields"]
        if renamed in inline_by_file:
            item["inline_object_pointers"] = inline_by_file[renamed]
        writable.append(item)
    description = "Read-only discovery index. .rw means at least one supported edit input, not that every field is writable. Each schema's editing section lists editable_fields and read_only_fields. .ro files have no supported edits. Raw byte strings/framing are advanced. Original bytes, IDs and structural constraints still apply."
    labeled["writable-index.ro.json"] = serialized({"access": "ro", "description": description, "files": writable})
    guide = ["# Writable DGN Files", "", description, "", "Edit the linked files, not this index. Unknown binary payloads and stream/framing edits are advanced operations.", "", "| File | Category | Edit Scope |", "|------|----------|------------|"]
    for item in writable:
        target = quote(item["file"], safe="/$^~@!()+,;=-.")
        guide.append(f"| [{item['file']}]({target}) | {item['category']} | {item['edit_scope']} |")
    labeled["WRITABLE.ro.md"] = ("\n".join(guide) + "\n").encode("utf-8")
    return labeled, renames


def label_workspace_files(folder: Path, manifest: dict, cancel=None) -> None:
    """Label or relabel an existing workspace folder; unrelated user files are preserved."""
    files = {}
    existing = set()
    for path in folder.rglob("*"):
        checkpoint(cancel)
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        existing.add(relative)
        if label_candidate(relative):
            files[relative] = path.read_bytes()
    labeled, renames = label_files(files, manifest, cancel, existing)
    store = FolderStore(folder, cancel)
    for relative, data in labeled.items():
        store.data(relative, data)
    for relative, target in renames.items():
        if relative != target and relative not in labeled:
            inside(folder, relative).unlink()


def checkpoint(cancel=None) -> None:
    if cancel is not None and cancel():
        raise InterruptedError("Operation cancelled")


def open_dgn(source: Path):
    olefile = ole_reader()
    with source.open("rb") as stream:
        if stream.read(8) != CFB_MAGIC:
            raise ValueError("Not a DGN V8 OLE compound file (DGN V7 is unsupported)")
    ole = olefile.OleFileIO(str(source))
    try:
        if not ole.exists("Dgn~H"):
            raise ValueError("Compound file has no Dgn~H stream; not a supported DGN")
        header = ole.openstream("Dgn~H").read(20)
        if len(header) != 20:
            raise ValueError("Truncated DGN header")
        if struct.unpack_from("<H", header)[0] & 2:
            raise ValueError("Encrypted DGN files are unsupported")
    except BaseException:
        ole.close()
        raise
    return ole


def extract_streams(ole, store: FolderStore | MemoryStore, original_sha256: str, limit: int, bytes_mode: str = "escaped", cancel=None, aggregate: int | None = None) -> dict:
    """Shared extraction core; `aggregate` bounds total decoded payload bytes."""
    manifest = {
        "format": FORMAT,
        "original_sha256": original_sha256,
        "storages": ole.listdir(streams=False, storages=True),
        "streams": [],
        "objects_index": "objects/index.json",
        "field_choices": "field-choices.json",
        "object_choices": "object-choices.json",
        "limitations": "Known metadata/attributes/chunk framing are editable; opaque geometry/application data, IDs, cross-stream indexes and signatures are not automatically repaired.",
    }
    objects = []
    total = 0
    for names in manifest["storages"]:
        checkpoint(cancel)
        store.directory("data/" + "/".join(map(disk_name, names)))
    for names in ole.listdir():
        checkpoint(cancel)
        if ole.get_size(names) > limit:
            raise ValueError(f"Stream exceeds --max-mib: {names!r}")
        raw = ole.openstream(names).read()
        codec, payload, prefix, suffix = decode_stream(names, raw, limit)
        total += len(payload)
        if aggregate is not None and total > aggregate:
            raise ValueError("Aggregate decoded limit exceeded")
        relative = "/".join(map(disk_name, names))
        payload_path = "data/" + relative + ".json"
        view = text_view(payload) or binary_view(payload)
        if names[-1].startswith("\x05"):
            view = properties_view(payload) or view
        if len(names) > 1 and names[-2].endswith("A") and names[-1].startswith("$"):
            view = attribute_sets_view(payload, limit) or view
        elif names[-1].startswith("$") and len(prefix) == 16:
            view = element_chunks_view(payload) or view
        elif names[-1] == "Dgn~Mh":
            view = model_header_view(payload) or view
        elif names == ["Dgn~H"]:
            view = design_header_view(payload) or view
        elif names == ["Dgn~Mf"]:
            view = manifest_view(payload)
        elif names == ["Dgn^Ix", "Dgn~Mix"]:
            view = model_index_view(payload, limit) or view
        if names[-1] == "^AH" and len(payload) == 4:
            view = {"kind": "uint32", "value": struct.unpack("<I", payload)[0]}
        externalize_text(store, relative, view)
        export_objects(store, relative, names, view, objects, bytes_mode)
        store.view(payload_path, view, bytes_mode)
        entry = {
            "ole_path": names,
            "file": payload_path,
            "representation": "json-view",
            "view_kind": view["kind"],
            "stream_role": stream_role(names),
            "codec": codec,
            "payload_sha256": digest(payload),
            "raw_sha256": digest(raw),
            "stored_bytes": len(raw),
            "extracted_bytes": len(payload),
        }
        if codec in ("zlib", "framed-raw"):
            for key, value in (("prefix", prefix), ("suffix", suffix)):
                relative_framing = f"framing/{relative}.{key}.json"
                framing_view = binary_view(value)
                if key == "prefix" and len(value) == 16:
                    count, flags, first, second = struct.unpack("<4I", value)
                    framing_view = {"kind": "dgn-block-header", "num_entries": count, "flags": flags, "reserved": [first, second]}
                elif key == "prefix" and len(value) == 20:
                    fields = struct.unpack("<2H4I", value)
                    framing_view = {"kind": "dgn-file-header", "flags": fields[0], "compression_level": fields[1], "encryption_data": list(fields[2:])}
                store.view(relative_framing, framing_view, bytes_mode)
                entry[key] = relative_framing
                entry[key + "_representation"] = "json-view"
                entry[key + "_sha256"] = digest(value)
        manifest["streams"].append(entry)
    store.view("objects/index.json", {"description": "Read-only discovery index. Edit referenced object/field/content files, not this index. Links/connections are never activated.", "objects": objects, "scope": "Text elements/nodes, supported EC text fields, DesignLinks XAttributes and type-66 database connections. Not an exhaustive embedded-file, EC data, database-linkage or external-reference inventory."})
    store.view("field-choices.json", field_choices())
    store.view("object-choices.json", object_choices())
    return manifest


def extract(source: Path, folder: Path, limit: int, bytes_mode: str = "escaped", cancel=None, labels: bool = True) -> dict:
    """Extract to a new folder, labeling in memory so each file is written once.

    `labels=False` writes the unlabeled legacy layout with manifest.json.
    """
    if bytes_mode not in ("escaped", "hex"):
        raise ValueError("bytes_mode must be escaped or hex")
    if folder.exists():
        raise ValueError(f"Destination already exists: {folder}")
    memory = MemoryStore()
    original = folder / "original.dgn"
    with open_dgn(source):
        folder.mkdir(parents=True)
        shutil.copyfile(source, original)
    with open_dgn(original) as ole:
        manifest = extract_streams(ole, memory, file_digest(original), limit, bytes_mode, cancel)
    memory.view("manifest.json", manifest)
    files = label_files(memory.files, manifest, cancel)[0] if labels else memory.files
    store = FolderStore(folder, cancel)
    for relative in sorted(memory.directories):
        store.directory(relative)
    created = set()
    for relative, data in files.items():
        checkpoint(cancel)
        path = inside(folder, relative)
        if path.parent not in created:
            path.parent.mkdir(parents=True, exist_ok=True)
            created.add(path.parent)
        path.write_bytes(data)
    return manifest


def extract_memory(source: Path, limit: int, bytes_mode: str = "escaped", cancel=None, aggregate: int | None = None) -> tuple[dict, dict[str, bytes]]:
    """Extract unlabeled workspace files in memory; nothing is written to disk."""
    if bytes_mode not in ("escaped", "hex"):
        raise ValueError("bytes_mode must be escaped or hex")
    store = MemoryStore()
    with open_dgn(source) as ole:
        manifest = extract_streams(ole, store, file_digest(source), limit, bytes_mode, cancel, aggregate)
    return manifest, store.files


def load_manifest(folder: Path | FolderStore | MemoryStore) -> dict:
    store = file_store(folder)
    name = "manifest.rw.json" if store.exists("manifest.rw.json") else "manifest.json"
    manifest = json.loads(store.read(name, DEFAULT_LIMIT).decode("utf-8"))
    if manifest.get("format") not in ("dgn-folder-v1", FORMAT):
        raise ValueError("Unsupported manifest format")
    paths = set()
    for names in manifest["storages"] + [entry["ole_path"] for entry in manifest["streams"]]:
        if not names or not all(isinstance(name, str) and name and len(name.encode("utf-16-le")) <= 62 and not any(char in name for char in "\\/:!\0") for name in names):
            raise ValueError(f"Invalid OLE path: {names!r}")
        key = tuple(name.upper() for name in names)
        if key in paths:
            raise ValueError(f"Duplicate OLE path: {names!r}")
        paths.add(key)
    storage_paths = {tuple(names) for names in manifest["storages"]} | {()}
    for names in manifest["storages"] + [entry["ole_path"] for entry in manifest["streams"]]:
        if tuple(names[:-1]) not in storage_paths:
            raise ValueError(f"Parent storage missing from manifest: {names!r}")
    return manifest


def encode_stream(folder: Path | FolderStore | MemoryStore, entry: dict, original: bytes | None, limit: int) -> bytes:
    counts = {}
    payload = read_view(folder, entry["file"], entry.get("representation"), limit, counts)
    previous = decode_stream(entry["ole_path"], original, limit) if original is not None else None
    if previous is not None and entry["ole_path"] == ["Dgn~H"] and entry["codec"] == "raw" and previous[0] == "framed-raw":
        previous = ("raw", original, b"", b"")
    if ".ro." in Path(entry["file"]).name and (previous is None or payload != previous[1]):
        raise ValueError(f"Read-only stream input changes: {entry['file']}")
    if entry["codec"] == "raw":
        return payload
    if entry["codec"] not in ("zlib", "framed-raw"):
        raise ValueError(f"Unsupported codec: {entry['codec']!r}")
    prefix = read_view(folder, entry["prefix"], entry.get("prefix_representation"), limit)
    suffix = read_view(folder, entry["suffix"], entry.get("suffix_representation"), limit)
    for key, value, index in (("prefix", prefix, 2), ("suffix", suffix, 3)):
        if ".ro." in Path(entry[key]).name and (previous is None or value != previous[index]):
            raise ValueError(f"Read-only framing input changes: {entry[key]}")
    if "num_entries" in counts and len(prefix) == 16:
        prefix = struct.pack("<I", counts["num_entries"]) + prefix[4:]
    if entry["codec"] == "framed-raw":
        if entry["ole_path"] == ["Dgn~H"]:
            if len(prefix) != 20 or struct.unpack_from("<H", prefix)[0] & 3:
                raise ValueError("Uncompressed Dgn~H framing must not set compressed/encrypted flags")
        elif len(prefix) != 16 or struct.unpack_from("<I", prefix, 4)[0] & 6:
            raise ValueError("Uncompressed block framing must not set compressed/encrypted flags")
        return prefix + payload + suffix
    if previous is not None:
        codec, old_payload, old_prefix, old_suffix = previous
        if codec == "zlib" and (payload, prefix, suffix) == (old_payload, old_prefix, old_suffix):
            return original
    return prefix + zlib.compress(payload, level=4) + suffix


def open_storage(root, names: tuple[str, ...], mode: int):
    chain = [root]
    for name in names:
        chain.append(chain[-1].OpenStorage(name, None, mode, None, 0))
    return chain


def update_compound(path: Path, storages: set[tuple[str, ...]], streams: set[tuple[str, ...]], changed: dict[tuple[str, ...], bytes], deleted: set[tuple[str, ...]], old_storages: set[tuple[str, ...]]) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Modified-file rebuild requires Windows and pywin32")
    try:
        import pythoncom
        from win32com import storagecon
    except ImportError as error:
        raise RuntimeError("Install dependency: python -m pip install pywin32") from error
    mode = storagecon.STGM_READWRITE | storagecon.STGM_SHARE_EXCLUSIVE
    root = pythoncom.StgOpenStorage(str(path), None, mode, None, 0)
    try:
        removed_storages = old_storages - storages
        removed = deleted | removed_storages
        top_removed = {names for names in removed if not any(names[:length] in removed_storages for length in range(1, len(names)))}
        for names in sorted(top_removed, key=len, reverse=True):
            chain = open_storage(root, names[:-1], mode)
            parent = chain[-1]
            parent.DestroyElement(names[-1])
            parent = None
            chain.clear()
        for names in sorted(storages - old_storages, key=len):
            chain = open_storage(root, names[:-1], mode)
            parent = chain[-1]
            child = parent.CreateStorage(names[-1], mode, 0, 0)
            child.Commit(0)
            child = parent = None
            chain.clear()
        for names, raw in changed.items():
            chain = open_storage(root, names[:-1], mode)
            parent = chain[-1]
            if names in streams:
                target = parent.OpenStream(names[-1], None, mode, 0)
            else:
                target = parent.CreateStream(names[-1], mode, 0, 0)
            target.SetSize(len(raw))
            cast(Any, target).Write(raw)
            target.Commit(0)
            target = parent = None
            chain.clear()
        root.Commit(0)
    finally:
        root = None


def rebuild(folder: Path, output: Path, limit: int, cancel=None, store: FolderStore | MemoryStore | None = None) -> int:
    """Rebuild from `folder/original.dgn`; `store` optionally supplies an in-memory workspace snapshot."""
    olefile = ole_reader()
    store = store or FolderStore(folder)
    manifest = load_manifest(store)
    original = folder / "original.dgn"
    if output.exists():
        raise ValueError(f"Output already exists; choose a new filename: {output}")
    if output.resolve().is_relative_to(folder.resolve()):
        raise ValueError("Output must be outside the extracted folder")
    if file_digest(original) != manifest["original_sha256"]:
        raise ValueError("original.dgn has changed; restore the extracted original")
    desired = {}
    changed = {}
    with olefile.OleFileIO(str(original)) as ole:
        old_streams = {tuple(names) for names in ole.listdir()}
        old_storages = {tuple(names) for names in ole.listdir(streams=False, storages=True)}
        for entry in manifest["streams"]:
            checkpoint(cancel)
            names = tuple(entry["ole_path"])
            raw = ole.openstream(list(names)).read() if names in old_streams else None
            encoded = encode_stream(store, entry, raw, limit)
            desired[names] = digest(encoded)
            if encoded != raw:
                changed[names] = encoded
    storages = {tuple(names) for names in manifest["storages"]}
    deleted = old_streams - desired.keys()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="dgn-rebuild-", suffix=".dgn", dir=output.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        shutil.copyfile(original, temporary_path)
        if changed or deleted or storages != old_storages:
            update_compound(temporary_path, storages, old_streams, changed, deleted, old_storages)
        with olefile.OleFileIO(str(temporary_path)) as ole:
            if {tuple(names) for names in ole.listdir()} != set(desired):
                raise ValueError("Rebuilt stream hierarchy verification failed")
            if {tuple(names) for names in ole.listdir(streams=False, storages=True)} != storages:
                raise ValueError("Rebuilt storage hierarchy verification failed")
            for names, expected in desired.items():
                checkpoint(cancel)
                if digest(ole.openstream(list(names)).read()) != expected:
                    raise ValueError(f"Rebuilt stream verification failed: {names!r}")
        if output.exists():
            raise ValueError(f"Output appeared during rebuild: {output}")
        checkpoint(cancel)
        os.rename(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return len(changed) + len(deleted) + len(storages.symmetric_difference(old_storages))


def legacy_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-mib", type=int, default=DEFAULT_LIMIT // (1024 * 1024), help="Maximum bytes per stored/decompressed stream, in MiB (default: 512)")
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", aliases=["unpack"], help="Extract V8 DGN streams into an editable folder")
    extract_parser.add_argument("source", type=Path)
    extract_parser.add_argument("folder", type=Path)
    extract_parser.add_argument("--bytes-mode", choices=("escaped", "hex"), default="escaped", help="Unknown bytes as reversible JSON strings (default), or legacy hex rows")
    rebuild_parser = commands.add_parser("rebuild", aliases=["pack"], help="Rebuild and verify streams, without overwriting an existing file")
    rebuild_parser.add_argument("folder", type=Path)
    rebuild_parser.add_argument("output", type=Path)
    inspect_parser = commands.add_parser("inspect", help="Inventory object types and metadata without resolving external targets")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.max_mib <= 0:
        parser.error("--max-mib must be positive")
    limit = arguments.max_mib * 1024 * 1024
    try:
        if arguments.command == "inspect":
            if arguments.output is not None and arguments.output.exists():
                raise ValueError(f"Output already exists: {arguments.output}")
            inventory = inspect_dgn(arguments.source.resolve(), limit)
            if arguments.output is None:
                print(json.dumps(inventory, indent=2, ensure_ascii=False))
            else:
                write_view(arguments.output, inventory)
                print(f"Inventoried {inventory['element_count']} elements in {inventory['model_count']} models to {arguments.output}")
        elif arguments.command in ("extract", "unpack"):
            manifest = extract(arguments.source.resolve(), arguments.folder.resolve(), limit, arguments.bytes_mode)
            compressed = sum(entry["codec"] == "zlib" for entry in manifest["streams"])
            print(f"Extracted {len(manifest['streams'])} streams ({compressed} decompressed) to {arguments.folder}")
            content = arguments.folder / "content"
            readable = sum(path.is_file() for path in content.rglob("*")) if content.exists() else 0
            print(f"Exported {readable} editable XML/JSON/text files under content/.")
            print("Open WRITABLE.ro.md for links to every editable .rw file; writable-index.ro.json provides a machine-readable index.")
            print(".ro files have no supported edits. .rw schemas list editable_fields and read_only_fields under editing; follow edit_warning.")
            print("Keep manifest.rw.json and original.dgn. Text extents/ranges and dependent metadata are not recalculated.")
            print("Unknown bytes use escaped strings or hex (--bytes-mode). No guessed object schemas; cross-object IDs/indexes/signatures are your responsibility.")
        else:
            count = rebuild(arguments.folder.resolve(), arguments.output.resolve(), limit)
            print(f"Rebuilt {arguments.output}: {count} changed entries; all stored streams verified.")
            if count:
                print("Binary container verification only. Validate object integrity by opening a copy in the DGN application.")
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    from dgn_explorer.cli import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())