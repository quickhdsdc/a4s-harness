"""Check identifier collisions in the configured BaSyx startup batch.

BaSyx milestone-15 rejects repeated Shell or Submodel IDs across loaded files,
even when those files contain identical objects. Dictionary IDs may recur across
packages. Cross-type collisions within a package are an additional SDK check.
This checks identifiers and ZIP integrity, not full metamodel conformance.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET
from zipfile import ZipFile

KINDS = ("assetAdministrationShells", "submodels", "conceptDescriptions")


def identifiers(name, data):
    if name.lower().endswith(".json"):
        document = json.loads(data)
        if not isinstance(document, dict):
            return []
        return [
            (kind, item["id"], item.get("idShort", ""))
            for kind in KINDS
            for item in document.get(kind, [])
        ]
    document = ET.fromstring(data)
    if document.tag.rsplit("}", 1)[-1] != "environment":
        return []
    return [
        (kind, item.findtext("{*}id"), item.findtext("{*}idShort", ""))
        for kind in KINDS
        for group in document.findall("{*}" + kind)
        for item in group
        if item.findtext("{*}id")
    ]


def startup_files(directory):
    config = directory.parent / "aas-env.properties"
    if not config.exists():
        return sorted(directory.iterdir())
    for line in config.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() != "basyx.environment":
            continue
        paths = []
        for entry in value.split(","):
            if not entry.strip().startswith("file:"):
                raise ValueError("Unsupported seed resource: " + entry)
            path = config.parent / entry.strip()[5:]
            if not path.exists():
                raise FileNotFoundError(path)
            paths.extend(sorted(path.rglob("*")) if path.is_dir() else [path])
        return paths
    raise ValueError("No active basyx.environment setting found")


def check(directory):
    failures, checked = [], 0
    loaded = {}
    for path in startup_files(directory):
        if path.suffix.lower() == ".aasx":
            with ZipFile(path) as archive:
                if bad := archive.testzip():
                    failures.append({"file": path.name, "error": "ZIP CRC: " + bad})
                manifest = minidom.parseString(archive.read("[Content_Types].xml"))
                if (manifest.documentElement.tagName != "Types" or
                    manifest.documentElement.namespaceURI !=
                        "http://schemas.openxmlformats.org/package/2006/content-types"):
                    failures.append({"file": path.name, "error":
                                     "AASX Explorer packaging compatibility: use an unprefixed Types root with the default content-types namespace"})
                manifest.unlink()
                parts = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name.lower().endswith((".xml", ".json"))
                }
        elif path.suffix.lower() == ".json":
            parts = {path.name: path.read_bytes()}
        else:
            continue
        found_environment = False
        for part, data in parts.items():
            rows = identifiers(part, data)
            if not rows:
                continue
            found_environment = True
            groups = defaultdict(list)
            for kind, identifier, label in rows:
                groups[identifier].append({"kind": kind, "idShort": label})
                if kind in ("assetAdministrationShells", "submodels"):
                    identity = (kind, identifier)
                    if identity in loaded:
                        failures.append({"file": path.name, "part": part,
                                         "duplicateId": identifier, "kind": kind,
                                         "previousFile": loaded[identity],
                                         "error": "Repeated identity in startup batch"})
                    else:
                        loaded[identity] = path.name
            for identifier, objects in groups.items():
                if len(objects) > 1:
                    failures.append({"file": path.name, "part": part,
                                     "duplicateId": identifier, "objects": objects})
        if not found_environment:
            failures.append({"file": path.name, "error": "No identifiable environment found"})
        checked += 1
    if checked == 0:
        failures.append({"error": "No seed packages found"})
    print(json.dumps({"packages": checked, "ok": not failures, "failures": failures}, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "BaSyxMinimal/aas")
    raise SystemExit(check(parser.parse_args().directory))
