from io import BytesIO
import json
from xml.etree.ElementTree import fromstring
from zipfile import ZipFile
import pytest

from a4s.server.aasx_export import package_environment, REL, AAS
from a4s.server import aas_routes


def test_package_relationships_and_nested_attachments():
    environment = {"assetAdministrationShells": [{"id": "device"}], "submodels": [{"id": "sm", "submodelElements": [
        {"modelType": "SubmodelElementList", "idShort": "Docs", "value": [
            {"modelType": "File", "value": "../../manual.pdf", "contentType": "application/pdf"},
            {"modelType": "File", "value": "https://example.org/manual.pdf"}]},
        {"modelType": "Property", "idShort": "Zero", "value": "0"}]}]}
    calls = []
    def load(sm, path):
        calls.append((sm, path))
        return b"%PDF-demo"
    with ZipFile(BytesIO(package_environment(environment, load))) as archive:
        assert archive.testzip() is None
        for member, kind in [("_rels/.rels", "aasx-origin"), ("aasx/_rels/aasx-origin.rels", "aas-spec"), ("aasx/_rels/data.json.rels", "aas-suppl")]:
            relation = fromstring(archive.read(member)).find(f"{{{REL}}}Relationship")
            assert relation.get("Type") == AAS + kind
            assert relation.get("Target").lstrip("/") in archive.namelist()
        exported = json.loads(archive.read("aasx/data.json"))
        file = exported["submodels"][0]["submodelElements"][0]["value"][0]
        assert archive.read(file["value"].lstrip("/")) == b"%PDF-demo"
        assert exported["submodels"][0]["submodelElements"][1]["value"] == "0"
    assert calls == [("sm", "Docs[0]")]
    assert environment["submodels"][0]["submodelElements"][0]["value"][0]["value"] == "../../manual.pdf"


def test_missing_attachment_is_not_silently_exported():
    with pytest.raises(ValueError, match="relative attachment"):
        package_environment({"submodels": [{"id": "sm", "submodelElements": [{"modelType": "File", "idShort": "Manual", "value": "/manual.pdf"}]}]})


def test_download_uses_selected_repository(monkeypatch):
    from fastapi import Response
    calls = []
    data = {"assetAdministrationShells": [{"id": "selected"}], "submodels": []}
    def exported(name, endpoint):
        calls.append((name, endpoint))
        return Response(json.dumps(data), headers={"Content-Disposition": 'attachment; filename="Device.json"'})
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(aas_routes, "download_json", exported)
    monkeypatch.setattr(aas_routes, "_client", lambda endpoint: Client())
    response = aas_routes.download_aasx("selected", "https://devices.example/aas")
    assert calls == [("selected", "https://devices.example/aas")]
    assert response.headers["Content-Disposition"] == 'attachment; filename="Device.aasx"'
    assert response.media_type == "application/aas+zip"
    with ZipFile(BytesIO(response.body)) as archive:
        assert json.loads(archive.read("aasx/data.json")) == data
