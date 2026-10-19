"""Read-only OPC/AASX packaging of a single exported AAS environment."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile

REL = "http://schemas.openxmlformats.org/package/2006/relationships"
AAS = "http://admin-shell.io/aasx/relationships/"
TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def _relationships(rows):
    root = Element("Relationships", xmlns=REL)
    for index, (kind, target) in enumerate(rows):
        SubElement(root, "Relationship", Id=f"r{index}", Type=AAS + kind, Target=target)
    return tostring(root, encoding="utf-8", xml_declaration=True)


def package_environment(environment, attachment_loader=None):
    """Keep external file URLs; embed relative files through the selected repo.

    Rewrites only the exported copy. No filesystem paths or external file URLs
    are opened. Missing relative attachments fail instead of producing a broken
    package. Nested collections, lists, entities and operation variables work.
    """
    data = deepcopy(environment)
    files = {}

    def visit(node, path, submodel_id):
        if isinstance(node, dict):
            if node.get("modelType") == "File" and node.get("value"):
                value = str(node["value"])
                if not urlsplit(value).scheme and not urlsplit(value).netloc:
                    if attachment_loader is None:
                        raise ValueError(f"Cannot export relative attachment at {path}")
                    payload = attachment_loader(submodel_id, path)
                    name = "aasx/suppl/" + sha256((submodel_id + "\n" + path).encode()).hexdigest()
                    files[name] = (payload, node.get("contentType") or "application/octet-stream")
                    node["value"] = "/" + name
            for key, children in node.items():
                if isinstance(children, list):
                    for index, child in enumerate(children):
                        if not isinstance(child, dict):
                            continue
                        if key in ("inputVariables", "outputVariables", "inoutputVariables"):
                            child = child.get("value", {})
                        if "modelType" not in child:
                            continue
                        segment = child.get("idShort")
                        child_path = (f"{path}[{index}]" if node.get("modelType") == "SubmodelElementList"
                                      else f"{path}.{segment}" if path else str(segment or ""))
                        visit(child, child_path, submodel_id)

    for submodel in data.get("submodels", []):
        visit(submodel, "", submodel["id"])
    types = Element("Types", xmlns=TYPES)
    SubElement(types, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    for name, content_type in [("aasx/aasx-origin", "text/plain"), ("aasx/data.json", "application/json")]:
        SubElement(types, "Override", PartName="/" + name, ContentType=content_type)
    for name, (_, content_type) in files.items():
        SubElement(types, "Override", PartName="/" + name, ContentType=content_type)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", tostring(types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", _relationships([("aasx-origin", "/aasx/aasx-origin")]))
        archive.writestr("aasx/aasx-origin", "Intentionally empty")
        archive.writestr("aasx/_rels/aasx-origin.rels", _relationships([("aas-spec", "/aasx/data.json")]))
        archive.writestr("aasx/data.json", json.dumps(data, ensure_ascii=False, indent=2))
        if files:
            archive.writestr("aasx/_rels/data.json.rels", _relationships([("aas-suppl", "/" + name) for name in files]))
        for name, (payload, _) in files.items():
            archive.writestr(name, payload)
    return output.getvalue()
