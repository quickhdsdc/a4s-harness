"""Normalize XML packaging syntax for AASX Explorer without changing model data.

The installed .NET packaging reader requires an unprefixed Types root. Its AAS
XML reader also rejects self-closing primitive values, including empty Blobs.
Preserve model namespace declarations and write empty elements with end tags.
The source is never overwritten: choose a separate output and verify it first.
"""
import argparse
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET
from zipfile import ZipFile

CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def normalize(source, output):
    if source.resolve() == output.resolve():
        raise ValueError("Choose a separate output file; preserve the input package")
    changed = []
    with ZipFile(source) as package:
        if bad := package.testzip():
            raise ValueError("Invalid ZIP member: " + bad)
        parts = {info.filename: package.read(info.filename) for info in package.infolist()}
        types = ET.fromstring(parts["[Content_Types].xml"])
        if types.tag != "{" + CONTENT_TYPES + "}Types":
            raise ValueError("Unexpected content-type manifest root")
        ET.register_namespace("", CONTENT_TYPES)
        parts["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8", xml_declaration=True)
        changed.append("[Content_Types].xml")
        for name in parts:
            if not name.endswith(".xml") or name == "[Content_Types].xml":
                continue
            document = minidom.parseString(parts[name])
            if document.documentElement.localName != "environment":
                document.unlink()
                continue
            # Empty text nodes force explicit start/end tags without inventing
            # characters, dropping optional values, or rewriting namespace QNames.
            for element in document.getElementsByTagName("*"):
                if not element.childNodes:
                    element.appendChild(document.createTextNode(""))
            parts[name] = document.toxml(encoding="utf-8")
            document.unlink()
            changed.append(name)
        with ZipFile(output, "w") as result:
            result.comment = package.comment
            for info in package.infolist():
                result.writestr(info, parts[info.filename])
    with ZipFile(output) as result:
        if bad := result.testzip():
            raise ValueError("Output ZIP CRC failure: " + bad)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("Normalized: " + ", ".join(normalize(args.source, args.output)))
