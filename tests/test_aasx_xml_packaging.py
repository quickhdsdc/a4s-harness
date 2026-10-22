"""Lock down the XML syntax that failed in the installed Explorer loader."""
import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

spec = importlib.util.spec_from_file_location(
    "normalize_aasx_xml", Path(__file__).resolve().parents[1] / "scripts/normalize-aasx-xml.py"
)
normalizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(normalizer)


def test_preserve_data_and_namespaces_while_fixing_xml_syntax(tmp_path):
    source, output = tmp_path / "source.aasx", tmp_path / "fixed.aasx"
    xml = (b'<aas:environment xmlns:aas="https://admin-shell.io/aas/3/1" '
           b'xmlns:custom="urn:example:qualifier-types"><aas:submodels><aas:submodel>'
           b'<aas:id>urn:agv</aas:id><aas:submodelElements><aas:blob>'
           b'<aas:idShort>EmptyBlob</aas:idShort><aas:contentType>custom:Data</aas:contentType>'
           b'<aas:value /></aas:blob></aas:submodelElements></aas:submodel>'
           b'</aas:submodels></aas:environment>')
    with ZipFile(source, "w") as archive:
        archive.writestr("[Content_Types].xml", (
            b'<ns0:Types xmlns:ns0="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<ns0:Default Extension="xml" ContentType="application/xml" /></ns0:Types>'
        ))
        archive.writestr("aasx/model.xml", xml)
        archive.writestr("aasx/photo.jpg", b"unchanged-image-bytes")
    original_bytes = source.read_bytes()
    normalizer.normalize(source, output)
    assert source.read_bytes() == original_bytes
    with ZipFile(output) as archive:
        fixed = archive.read("aasx/model.xml")
        assert b"<aas:value></aas:value>" in fixed
        assert b'xmlns:custom="urn:example:qualifier-types"' in fixed
        assert b'<Types xmlns="' in archive.read("[Content_Types].xml")
        assert archive.read("aasx/photo.jpg") == b"unchanged-image-bytes"
        assert ET.tostring(ET.fromstring(fixed)) == ET.tostring(ET.fromstring(xml))


def test_requires_separate_output(tmp_path):
    source = tmp_path / "source.aasx"
    with pytest.raises(ValueError, match="separate output"):
        normalizer.normalize(source, source)
