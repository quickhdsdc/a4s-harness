"""Discover canonical blueprint IDs and copy from the source into the target."""
from contextlib import nullcontext
import copy

from fastapi.testclient import TestClient
import pytest

from a4s.aasctl.client import AasHttpError
from a4s.server import build_app, aas_routes, write_routes


class Repository:
    def __init__(self, shells=(), submodels=()):
        self.shells = {item["id"]: copy.deepcopy(item) for item in shells}
        self.submodels = {item["id"]: copy.deepcopy(item) for item in submodels}

    def list_shells(self, **kwargs):
        return list(self.shells.values())

    def get_shell(self, identifier):
        if identifier not in self.shells:
            raise AasHttpError(404, "http://test/shells", "missing")
        return copy.deepcopy(self.shells[identifier])

    def list_submodel_refs(self, identifier):
        return self.get_shell(identifier).get("submodels", [])

    def get_submodel(self, identifier):
        return copy.deepcopy(self.submodels[identifier])

    def create_submodel(self, item):
        self.submodels[item["id"]] = copy.deepcopy(item)

    def create_shell(self, item):
        self.shells[item["id"]] = copy.deepcopy(item)

    def delete_submodel(self, identifier):
        self.submodels.pop(identifier, None)


@pytest.fixture
def repositories(monkeypatch):
    blueprint = {"id": "urn:new-publisher:blueprint:lathe", "idShort": "Lathe",
                 "assetInformation": {"assetKind": "Type"},
                 "submodels": [{"keys": [{"type": "Submodel", "value": "urn:source:technical"}]}]}
    catalog = {"id": "urn:catalog", "idShort": "CollectionofSMTs",
               "assetInformation": {"assetKind": "Type"}}
    data = {"id": "urn:source:technical", "idShort": "TechnicalData", "kind": "Instance",
            "submodelElements": [{"modelType": "Property", "idShort": "Manufacturer",
                                  "valueType": "xs:string", "value": "Example"}]}
    source = Repository([blueprint, catalog], [data])
    target = Repository()
    monkeypatch.setenv("A4S_SMT_ENDPOINT", "http://library")
    monkeypatch.delenv("A4S_BLUEPRINT_ENDPOINT", raising=False)
    monkeypatch.setenv("A4S_AAS_ENDPOINT", "http://target")

    def factory(endpoint=None):
        return nullcontext(source if endpoint == "http://library" else target)

    monkeypatch.setattr(aas_routes, "_client", factory)
    monkeypatch.setattr(write_routes, "_client", factory)
    monkeypatch.setattr(write_routes, "_recorded", lambda *args, **kwargs: None)
    return TestClient(build_app("http://target")), source, target


def test_discovery_returns_current_ids_and_excludes_smt_catalog(repositories):
    api, source, target = repositories
    response = api.get("/api/blueprints")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["id"] == "urn:new-publisher:blueprint:lathe"
    assert rows[0]["endpoint"] == "http://library"
    assert not target.shells


def test_instantiation_reads_current_source_refs_and_only_writes_target(repositories):
    api, source, target = repositories
    original = copy.deepcopy((source.shells, source.submodels))
    response = api.post("/api/instantiate-aas", json={
        "blueprint_id": "urn:new-publisher:blueprint:lathe",
        "blueprint_endpoint": "http://library", "endpoint": "http://target",
        "new_aas_id": "urn:device:lathe", "new_aas_id_short": "Lathe_1",
    })
    assert response.status_code == 200, response.text
    assert response.json()["blueprint_id"] == "urn:new-publisher:blueprint:lathe"
    assert target.shells["urn:device:lathe"]["idShort"] == "Lathe_1"
    assert target.submodels["urn:device:lathe/sm/TechnicalData"]["submodelElements"][0]["value"] == "Example"
    assert (source.shells, source.submodels) == original
