"""Build a verified passive DGN regression corpus, not an all-feature authoring engine.

python dgn_fixture_catalog.py sources corpus --max-files 80
Source files remain untouched. External targets and startup data are not activated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

import dgn_folder as tool


SAMPLE_URL = "https://example.invalid/dgn-explorer-marker"
SAMPLE_FILE = "dgn-explorer-marker.txt"
FEATURE_WORDS = ("sample", "element", "embedded", "reference", "link", "schema", "item", "mesh", "solid", "tag", "raster", "cell", "material", "text", "dimension", "building", "abdfile", "ba_test")


def candidates(root: Path, maximum: int) -> list[Path]:
    roots = [root / "PowerPlatform/DgnPlatformTest/data", root / "OpenBuildings/spaceplanner/src", root / "PowerPlatform/MstnPlatform/mstn/testapps/MSTestRunner/tests/ToolScripting/TestData", root / "PowerPlatform/MstnPlatform/PPModules/bimbridge/imodelbridgeaffinitytest/TestData"]
    paths = []
    for directory in roots:
        if directory.exists():
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() == ".dgn" and path.stat().st_size <= 32 * 1024 * 1024 and any(word in path.name.lower() for word in FEATURE_WORDS):
                    paths.append(path)
    def priority(path: Path) -> tuple:
        featured = path.name.lower() in ("ba_test_file_office.dgn", "abdfile.dgn", "designlinkstest.dgn", "elements.dgn", "v8_withembeddedjpg.dgn")
        return (0 if featured else 1, len(path.parts), str(path).lower())
    return sorted(set(paths), key=priority)[:maximum]


def build_catalog(root: Path, output: Path, maximum: int, verify_count: int) -> dict:
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    output.mkdir(parents=True)
    inventories = []
    failures = []
    for source in candidates(root, maximum):
        print(f"Inventory: {source.name}", flush=True)
        try:
            inventories.append(tool.inspect_dgn(source, 64 * 1024 * 1024))
        except Exception as error:
            failures.append({"source": str(source), "reason": str(error)})
    if not inventories:
        raise ValueError("No supported DGN fixture is available")
    ranked = sorted(inventories, key=lambda item: (len(item["model_element_types"]), len(item["attribute_handlers"]), len(item["string_linkage_keys"])), reverse=True)
    selected = []
    covered = set()
    for item in ranked:
        features = {f"element:{entry['type']}" for entry in item["model_element_types"]}
        features.update(f"handler:{entry['handler_id']}" for entry in item["attribute_handlers"])
        features.update(f"string:{entry['key']}" for entry in item["string_linkage_keys"])
        if not selected or features - covered:
            selected.append(item)
            covered.update(features)
        if len(selected) >= verify_count:
            break
    verified = []
    for index, item in enumerate(selected):
        source = Path(item["source"])
        filename = f"{index + 1:02d}-" + source.name
        target = output / "fixtures" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(f"Verify: {filename}", flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix="dgn-rich-fixture-") as temporary:
                folder = Path(temporary) / "unpacked"
                rebuilt = Path(temporary) / "repacked.dgn"
                tool.extract(target, folder, 64 * 1024 * 1024)
                changes = tool.rebuild(folder, rebuilt, 64 * 1024 * 1024)
                if changes or tool.file_digest(rebuilt) != item["sha256"]:
                    raise ValueError("Fixture does not rebuild byte-identically")
        except Exception as error:
            failures.append({"source": str(source), "reason": str(error), "stage": "roundtrip"})
            continue
        verified.append({"file": "fixtures/" + filename, "source": str(source), "sha256": item["sha256"], "byte_identical_roundtrip": True, "inventory": item})
    if not verified:
        raise ValueError("No fixture passes byte-identical roundtrip verification")
    baseline = output / "rich-sample.dgn"
    shutil.copyfile(output / verified[0]["file"], baseline)
    tool.extract(baseline, output / "rich-sample-unpacked", 64 * 1024 * 1024)
    tool.rebuild(output / "rich-sample-unpacked", output / "rich-sample-repacked.dgn", 64 * 1024 * 1024)
    result = {"description": "Rich real fixture plus complementary verified corpus, not a fabricated combined/all-feature OBD file.", "baseline": "rich-sample.dgn", "baseline_inventory": verified[0]["inventory"], "verified_fixtures": verified, "inventories": inventories, "skipped": failures, "observed_coverage": sorted(covered), "all_openbuildings_features": False, "sample_targets": {"url": SAMPLE_URL, "file_link": SAMPLE_FILE, "activated": False}, "authoring_blocker": "A combined feature fixture requires OpenBuildings authoring/SDK APIs to create/copy/remap domain objects, EC data, dependencies, attachments and embedded resources. Raw concatenation cannot establish validity.", "safety": "Existing fixtures can retain active content and external targets. Verification is passive container verification. Open copies only in an isolated Bentley environment with network and application/startup execution controlled."}
    tool.write_view(output / "catalog.json", result)
    return result


def retarget_link_xml(root: ET.Element) -> str | None:
    if root.tag != "DgnLinkNode":
        return None
    handler = root.findtext("NodeData/Handler")
    if handler == "URLLink":
        url = root.find("HandlerData/{*}URLLink/{*}URL")
        if url is not None and url.text and not url.text.lower().startswith("ustnkeyin:"):
            url.text = SAMPLE_URL
            name = root.find("NodeData/Name")
            if name is not None:
                name.text = SAMPLE_URL
            return "url"
    elif handler == "FileLink":
        moniker = root.find("HandlerData/{*}FileLink/{*}Moniker")
        if moniker is not None and moniker.text:
            inner = ET.fromstring(moniker.text)
            if inner.tag == "MSDocMoniker":
                filename = inner.find("FileName")
                fullpath = inner.find("FullPath")
                if filename is not None and fullpath is not None:
                    filename.text = SAMPLE_FILE
                    fullpath.text = SAMPLE_FILE
                    moniker.text = ET.tostring(inner, encoding="unicode")
                    name = root.find("NodeData/Name")
                    if name is not None:
                        name.text = SAMPLE_FILE
                    return "file_link"
    return None


def augment_catalog(output: Path) -> dict:
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    names = ("V8_withEmbeddedJPG.dgn", "ABDfile.dgn", "DesignLinksTest.dgn", "Links.dgn")
    supplemental = []
    for name in names:
        item = next((item for item in catalog["inventories"] if Path(item["source"]).name == name), None)
        if item is None:
            continue
        source = Path(item["source"])
        filename = "extra-" + source.name
        destination = output / "fixtures" / filename
        if destination.exists():
            raise ValueError(f"Supplemental fixture already exists: {destination}")
        shutil.copyfile(source, destination)
        with tempfile.TemporaryDirectory(prefix="dgn-extra-fixture-") as temporary:
            folder = Path(temporary) / "unpacked"
            rebuilt = Path(temporary) / "repacked.dgn"
            tool.extract(destination, folder, 64 * 1024 * 1024)
            changes = tool.rebuild(folder, rebuilt, 64 * 1024 * 1024)
            if changes or tool.file_digest(rebuilt) != item["sha256"]:
                raise ValueError(f"Supplemental fixture fails byte-identical rebuild: {source}")
        supplemental.append({"file": "fixtures/" + filename, "source": str(source), "sha256": item["sha256"], "byte_identical_roundtrip": True, "inventory": item})
    source = next(Path(item["source"]) for item in catalog["inventories"] if Path(item["source"]).name == "Links.dgn")
    folder = output / "interaction-unpacked"
    tool.extract(source, folder, 64 * 1024 * 1024)
    mutations = []
    for path in (folder / "content").rglob("*.xml"):
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        kind = retarget_link_xml(root)
        if kind:
            path.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
            mutations.append({"file": str(path.relative_to(folder)), "kind": kind})
    if not any(item["kind"] == "url" for item in mutations) or not any(item["kind"] == "file_link" for item in mutations):
        raise ValueError("Interaction sample does not contain both actual URL and file-link mutations")
    edited = output / "interaction-sample.dgn"
    changes = tool.rebuild(folder, edited, 64 * 1024 * 1024)
    second = output / "interaction-reextracted"
    tool.extract(edited, second, 64 * 1024 * 1024)
    for mutation in mutations:
        path = second / mutation["file"]
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        if mutation["kind"] == "url":
            if root.findtext("HandlerData/{*}URLLink/{*}URL") != SAMPLE_URL:
                raise ValueError("URL target does not survive repacking")
        else:
            inner = ET.fromstring(root.findtext("HandlerData/{*}FileLink/{*}Moniker", ""))
            if inner.findtext("FullPath") != SAMPLE_FILE:
                raise ValueError("File target does not survive repacking")
    second_repack = output / "interaction-repacked.dgn"
    if tool.rebuild(second, second_repack, 64 * 1024 * 1024) or tool.file_digest(second_repack) != tool.file_digest(edited):
        raise ValueError("Interaction sample does not roundtrip byte-identically after edits")
    catalog["verified_fixtures"].extend(supplemental)
    catalog["interaction_sample"] = {"file": "interaction-sample.dgn", "changed_streams": changes, "mutations": mutations, "byte_identical_after_edit_roundtrip": True, "targets": {"url": SAMPLE_URL, "file_link": SAMPLE_FILE}, "activated": False, "application_rendering_verified": False}
    tool.write_view(output / "catalog.json", catalog)
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--verify-count", type=int, default=6)
    parser.add_argument("--augment", action="store_true", help="Add explicit raster/OBD/link fixtures and verified passive interaction mutations to an existing generated catalogue")
    arguments = parser.parse_args()
    if arguments.max_files <= 0 or arguments.verify_count <= 0:
        parser.error("Counts must be positive")
    result = augment_catalog(arguments.output.resolve()) if arguments.augment else build_catalog(arguments.sources.resolve(), arguments.output.resolve(), arguments.max_files, arguments.verify_count)
    print(f"Verified {len(result['verified_fixtures'])} fixtures. Baseline: {arguments.output / 'rich-sample.dgn'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())