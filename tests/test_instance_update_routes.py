"""Public REST adapter tests with independent template and production repositories."""

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a4s.server import aas_routes, update_routes, wizard_routes
from test_instance_updates import Repository, prop
from test_automatic_updates import fixture_categories


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(update_routes.automatic_updates, 'classify_categories', fixture_categories)
    target, source = Repository(), Repository()
    source.models = {
        "urn:template": {
            "id": "urn:template",
            "idShort": "Nameplate",
            "modelType": "Submodel",
            "kind": "Template",
            "administration": {"version": "2", "revision": "0"},
            "submodelElements": [prop("Manufacturer"), prop("SerialNumber")],
        }
    }
    source.shells["https://example.com/ids/aas/CollectionofSMTs"] = {
        "submodels": [{"keys": [{"type": "Submodel", "value": "urn:template"}]}]
    }
    monkeypatch.setenv("A4S_HOME", str(tmp_path))
    monkeypatch.setenv("A4S_WEB_WORKSPACE", str(tmp_path / "web"))
    monkeypatch.setenv("A4S_AAS_ENDPOINT", "http://production")
    monkeypatch.setenv("A4S_SMT_ENDPOINT", "http://templates")
    monkeypatch.setenv("A4S_SMT_COLLECTION", "https://example.com/ids/aas/CollectionofSMTs")

    def client(endpoint=None):
        return source if endpoint == "http://templates" else target

    monkeypatch.setattr(aas_routes, "_client", client)
    monkeypatch.setattr(wizard_routes, "_client", client)
    monkeypatch.setattr(wizard_routes, "_recorded", lambda *a: None)
    app = FastAPI()
    app.include_router(update_routes.router)
    app.include_router(wizard_routes.router)
    return TestClient(app), target, source


def test_prepare_review_commit_and_snapshots_use_the_production_repository(monkeypatch, tmp_path):
    client, target, source = setup(monkeypatch, tmp_path)
    result = client.get(
        "/api/instance-updates/discover",
        params={"aas": "urn:device", "endpoint": "http://production"},
    )
    assert result.status_code == 200, result.text
    release = result.json()["templates"][0]
    before = copy.deepcopy(target.models)
    prepared = client.post(
        "/api/instance-updates/prepare",
        json={
            "aas": "urn:device",
            "endpoint": "http://production",
            "selections": [
                {
                    "templateId": "urn:template",
                    "releaseHash": release["hash"],
                    "mode": "enrich",
                    "targetId": "urn:plate",
                }
            ],
        },
    ).json()
    identifier = prepared["id"]
    properties = client.get(f"/api/instance-updates/{identifier}/properties").json()
    assert "SerialNumber" in {p["idShort"] for p in properties["properties"]}
    row = {
        "extractedEntity": "Serial number",
        "extractedValue": "SN123",
        "aasProperty": "SerialNumber",
        "aasType": "Property",
        "targetType": "Property",
        "submodelId": "urn:plate",
        "apiPath": "SerialNumber",
        "action": "write",
        "selected": True,
    }
    response = client.post(f"/api/instance-updates/{identifier}/review", json={"results": [row]})
    assert response.status_code == 200, response.text
    assert target.models == before and not target.writes
    response = client.post(
        f"/api/instance-updates/{identifier}/commit",
        json={"reviewHash": response.json()["reviewHash"]},
    )
    assert response.status_code == 200 and response.json()["success"], response.text
    assert not source.writes
    assert (
        client.get(f"/api/instance-updates/{identifier}/snapshot").json()["before"]["submodels"][
            "urn:plate"
        ]
        == before["urn:plate"]
    )


def test_archived_release_remains_selectable_after_same_id_is_republished(monkeypatch, tmp_path):
    client, _, source = setup(monkeypatch, tmp_path)
    params = {"aas": "urn:device", "endpoint": "http://production"}
    old = client.get("/api/instance-updates/discover", params=params).json()["templates"][0]
    source.models["urn:template"]["administration"]["version"] = "3"
    response = client.get("/api/instance-updates/discover", params=params).json()
    assert {entry["version"] for entry in response["templates"]} == {"2", "3"}
    assert next(entry for entry in response["templates"] if entry["hash"] == old["hash"])[
        "archived"
    ]


def test_invalid_update_match_does_not_leave_the_wizard_locked(monkeypatch, tmp_path):
    client, _, _ = setup(monkeypatch, tmp_path)
    response = client.post(
        "/api/match",
        json={"filename": "input.pdf", "aas_id_short": "Device", "update_id": "missing"},
    )
    assert response.status_code == 422
    assert not wizard_routes.WIZARD_LOCK.locked()


def test_update_cannot_be_used_against_another_repository(monkeypatch, tmp_path):
    client, _, _ = setup(monkeypatch, tmp_path)
    identifier = client.post(
        "/api/instance-updates/prepare", json={"aas": "urn:device", "endpoint": "http://production"}
    ).json()["id"]
    response = client.post(
        f"/api/instance-updates/{identifier}/review",
        json={"endpoint": "http://templates", "results": []},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("pinned", [False, True])
def test_prepare_accepts_valid_templates_without_a_second_collection_check(monkeypatch, tmp_path, pinned):
    client, target, source = setup(monkeypatch, tmp_path)
    outside = copy.deepcopy(source.models["urn:template"])
    outside["id"] = "urn:outside-collection"
    source.models[outside["id"]] = outside
    selection = {"templateId": outside["id"], "mode": "add", "targetId": ""}
    if pinned:
        selection["releaseHash"] = update_routes._store().release("http://templates", outside)[
            "hash"
        ]
    before = copy.deepcopy(target.models)
    response = client.post(
        "/api/instance-updates/prepare",
        json={"aas": "urn:device", "endpoint": "http://production", "selections": [selection]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"
    assert target.models == before and not target.writes and not source.writes


def test_removed_template_is_not_offered_from_the_archive(monkeypatch, tmp_path):
    client, _, source = setup(monkeypatch, tmp_path)
    params = {"aas": "urn:device", "endpoint": "http://production"}
    assert client.get("/api/instance-updates/discover", params=params).json()["templates"]
    source.shells["https://example.com/ids/aas/CollectionofSMTs"]["submodels"] = []
    assert client.get("/api/instance-updates/discover", params=params).json()["templates"] == []
    assert client.get("/api/instance-updates/catalog").json() == []


def test_automatic_edit_needs_only_templates_and_lists_existing_instances(monkeypatch, tmp_path):
    client, target, source = setup(monkeypatch, tmp_path)
    inventory = client.get(
        "/api/instance-updates/existing",
        params={"aas": "urn:device", "endpoint": "http://production"},
    )
    assert inventory.status_code == 200
    assert inventory.json()["submodels"][0]["id"] == "urn:plate"
    response = client.post(
        "/api/instance-updates/prepare",
        json={
            "aas": "urn:device",
            "endpoint": "http://production",
            "templateIds": ["urn:template"],
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["automatic"]
    assert draft["replacementGroups"][0]["replaces"] == ["urn:plate"]
    assert not target.writes and not source.writes
    response = client.post(
        "/api/instance-updates/prepare",
        json={"aas": "urn:device", "endpoint": "http://production", "templateIds": ["urn:outside"]},
    )
    assert response.status_code == 404
    assert "Cannot read AAS update resource" in response.json()["detail"]


def test_prepare_does_not_revalidate_collection_membership_after_selection(monkeypatch, tmp_path):
    client, target, source = setup(monkeypatch, tmp_path)
    # The selected template still exists; only the catalog AAS was edited.
    source.shells["https://example.com/ids/aas/CollectionofSMTs"]["submodels"] = []
    response = client.post(
        "/api/instance-updates/prepare",
        json={"aas": "urn:device", "endpoint": "http://production", "templateIds": ["urn:template"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["automatic"]
    assert not target.writes and not source.writes


def test_prepare_still_requires_an_actual_template_resource(monkeypatch, tmp_path):
    client, target, source = setup(monkeypatch, tmp_path)
    source.models["urn:template"]["kind"] = "Instance"
    response = client.post(
        "/api/instance-updates/prepare",
        json={"aas": "urn:device", "endpoint": "http://production", "templateIds": ["urn:template"]},
    )
    assert response.status_code == 422
    assert "not an SMT" in response.json()["detail"]
    assert not target.writes and not source.writes


@pytest.mark.parametrize(
    "element",
    [
        {
            "modelType": "File",
            "idShort": "Evidence",
            "value": "manual.pdf",
            "contentType": "application/pdf",
        },
        {
            "modelType": "ReferenceElement",
            "idShort": "Evidence",
            "value": {
                "type": "ExternalReference",
                "keys": [{"type": "GlobalReference", "value": "https://example.com/record"}],
            },
        },
        {
            "modelType": "Blob",
            "idShort": "Evidence",
            "value": "SGVsbG8=",
            "contentType": "text/plain",
        },
        {
            "modelType": "Range",
            "idShort": "Evidence",
            "valueType": "xs:int",
            "min": "0",
            "max": "5",
        },
        {
            "modelType": "MultiLanguageProperty",
            "idShort": "Evidence",
            "value": [
                {"language": "en", "text": "Evidence"},
                {"language": "de", "text": "Nachweis"},
            ],
        },
    ],
)
def test_native_existing_value_can_be_recreated_at_submodel_root(monkeypatch, tmp_path, element):
    client, target, source = setup(monkeypatch, tmp_path)
    target.models["urn:plate"]["submodelElements"] = [copy.deepcopy(element)]
    source.models["urn:template"]["submodelElements"] = []
    draft = client.post(
        "/api/instance-updates/prepare",
        json={
            "aas": "urn:device",
            "endpoint": "http://production",
            "templateIds": ["urn:template"],
        },
    ).json()
    fact = update_routes._store().get(draft["id"])["legacyInputs"][0]
    sm_id = draft["replacementGroups"][0]["candidateId"]
    result = client.post(
        f"/api/instance-updates/{draft['id']}/review",
        json={
            "results": [
                {
                    "extractedEntity": "Evidence",
                    "extractedValue": fact["value"],
                    "aasProperty": "Evidence",
                    "apiPath": "",
                    "targetType": "Submodel",
                    "submodelId": sm_id,
                    "aasType": element["modelType"],
                    "action": "create",
                    "selected": True,
                    "source": fact["source"],
                }
            ]
        },
    )
    assert result.status_code == 200, result.text
    reviewed = update_routes._store().get(draft["id"])["reviewed"]["submodels"][sm_id]
    actual = reviewed["submodelElements"][0]
    assert {key: actual[key] for key in element} == element
    assert not target.writes and not source.writes
