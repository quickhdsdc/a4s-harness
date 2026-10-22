import argparse
import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a4s.aasctl.population_cleanup import remove_empty_properties
from a4s.aasctl.paths import ElementPath
from a4s.server import aas_routes, wizard_routes


def prop(name, value=None, kind="Property"):
    return {"modelType": kind, "idShort": name, "valueType": "xs:string", "value": value}


class Repository:
    def __init__(self, submodels):
        self.submodels = {s["id"]: copy.deepcopy(s) for s in submodels}
        self.deleted = []

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get_submodel(self, identifier): return copy.deepcopy(self.submodels[identifier])
    def get_shell(self, identifier):
        assert identifier == "urn:aas:chosen"
        return {"id": identifier, "idShort": "Chosen"}
    def list_submodel_refs(self, identifier):
        assert identifier == "urn:aas:chosen"
        return [{"keys": [{"type": "Submodel", "value": key}]} for key in ("urn:sm:chosen", "urn:sm:other")]

    def children(self, node):
        return node.get("submodelElements", node.get("statements", node.get("value", [])))

    def locate(self, identifier, path):
        node = self.submodels[identifier]
        for step in path.steps:
            children = self.children(node)
            node = children[step] if isinstance(step, int) else next(c for c in children if c.get("idShort") == step)
        return node

    def delete_element(self, identifier, path):
        parent = self.locate(identifier, ElementPath(path.steps[:-1]))
        children = self.children(parent)
        step = path.steps[-1]
        index = step if isinstance(step, int) else next(i for i, c in enumerate(children) if c.get("idShort") == step)
        children.pop(index)
        self.deleted.append((identifier, str(path)))

    def add_element(self, identifier, path, element):
        self.children(self.locate(identifier, path)).append(element)


def sm(identifier="urn:sm:chosen", elements=None, kind="Instance"):
    return {"id": identifier, "idShort": "TechnicalData", "kind": kind,
            "modelType": "Submodel", "submodelElements": elements or []}


def test_cleanup_nested_properties_preserves_zero_false_languages_and_other_smes():
    repository = Repository([sm(elements=[prop("Blank", " "), prop("Zero", 0), prop("False", False),
        prop("Translated", [{"language": "en", "text": ""}, {"language": "de", "text": "Wert"}], "MultiLanguageProperty"),
        prop("EmptyTranslation", [{"language": "en", "text": " "}], "MultiLanguageProperty"),
        prop("EmptyFile", "", "File"),
        {"modelType": "Entity", "idShort": "Entity", "statements": [prop("Missing")]},
        {"modelType": "SubmodelElementList", "idShort": "List", "value": [prop(None), prop(None, "kept"), prop(None)]},
        {"modelType": "SubmodelElementCollection", "idShort": "Collection", "value": [prop("Missing")]},
    ]), sm("urn:smt", [prop("TemplateSlot")], kind="Template")])
    result = remove_empty_properties(repository, ["urn:sm:chosen", "urn:smt"])
    assert result["status"] == "completed" and not result["failed"]
    assert set(path for _, path in repository.deleted) == {"Blank", "EmptyTranslation", "Entity.Missing", "List[2]", "List[0]", "Collection.Missing", "Collection"}
    assert repository.deleted.index(("urn:sm:chosen", "List[2]")) < repository.deleted.index(("urn:sm:chosen", "List[0]"))
    remaining = {n["idShort"]: n for n in repository.submodels["urn:sm:chosen"]["submodelElements"]}
    assert remaining["Zero"]["value"] == 0 and remaining["False"]["value"] is False
    assert remaining["List"]["value"][0]["value"] == "kept"
    assert remaining["EmptyFile"] and remaining["Translated"]
    assert repository.submodels["urn:smt"]["submodelElements"] == [prop("TemplateSlot")]


@pytest.mark.parametrize("failed_path", [None, "List[2].Inner.Blank", "List[2].Inner"])
def test_cleanup_prunes_nested_empty_collections_only_after_successful_child_deletion(failed_path):
    def collection(name, children):
        return {"modelType": "SubmodelElementCollection", "idShort": name, "value": children}
    repository = Repository([sm(elements=[
        collection("AlreadyEmpty", []),
        collection("Keep", [prop("Zero", 0), collection("Empty", [])]),
        {"modelType": "SubmodelElementList", "idShort": "List", "value": [
            collection(None, []), collection(None, [prop("Data", "kept")]),
            collection(None, [collection("Inner", [prop("Blank")])]),
        ]},
    ])])
    delete = repository.delete_element
    def delete_with_failure(identifier, path):
        if str(path) == failed_path:
            raise RuntimeError("deletion failed")
        delete(identifier, path)
    repository.delete_element = delete_with_failure
    result = remove_empty_properties(repository, ["urn:sm:chosen"])
    assert result["status"] == ("incomplete" if failed_path else "completed")
    nodes = repository.submodels["urn:sm:chosen"]["submodelElements"]
    assert [node["idShort"] for node in nodes] == ["Keep", "List"]
    assert nodes[0]["value"] == [prop("Zero", 0)]
    assert nodes[1]["value"][0]["value"] == [prop("Data", "kept")]
    assert len(nodes[1]["value"]) == (2 if failed_path else 1)
    if failed_path:
        assert ("urn:sm:chosen", "List[2]") not in repository.deleted
        assert result["failed"][0]["path"] == failed_path
    else:
        paths = [path for _, path in repository.deleted]
        assert paths.index("List[2].Inner.Blank") < paths.index("List[2].Inner") < paths.index("List[2]") < paths.index("List[0]")


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("A4S_WEB_WORKSPACE", str(tmp_path))
    repository = Repository([sm(elements=[prop("Blank"), prop("Existing", "kept")]),
                             sm("urn:sm:other", [prop("Blank")]),
                             sm("urn:sm:unrelated", [prop("Unrelated")])])
    monkeypatch.setattr(wizard_routes, "_client", lambda endpoint: repository)
    monkeypatch.setattr(aas_routes, "_client", lambda endpoint: repository)
    monkeypatch.setattr(wizard_routes, "_recorded", lambda *args: None)
    app = FastAPI()
    app.include_router(wizard_routes.router)
    app.include_router(aas_routes.router)
    with TestClient(app) as client:
        yield client, repository


def root_plan(client):
    response = client.post("/api/save-matching-results", json={"filename": "battery", "aas_id_short": "urn:aas:chosen", "results": [{
        "extractedEntity": "Communication interfaces", "extractedValue": "CAN / ModBus",
        "aasProperty": "OldSuggestion", "aasType": "Property", "action": "write", "apiPath": "Old.Path",
        "submodelId": "urn:sm:other", "aasProperties": [{"type": "Submodel", "idShort": "TechnicalData",
        "apiPath": "", "semanticPath": "TechnicalData/", "submodelId": "urn:sm:chosen", "submodelIdShort": "TechnicalData"}]
    }]})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["count"] == 1 and not saved["unresolved"]
    return saved


def test_manual_submodel_selection_creates_at_root_then_cleans_only_chosen_aas(api):
    client, repository = api
    saved = root_plan(client)
    plan = json.loads(Path(saved["plans"][0]["path"]).read_text())
    decision = plan["decisions"][0]
    assert decision["action"] == "create" and decision["path"] == ""
    assert decision["model_type"] == "Property" and decision["id_short"] == "Communication_interfaces"
    result = client.post("/api/populate", json={"filename": Path(saved["path"]).name, "aas_id_short": "urn:aas:chosen"}).json()
    assert result["success"], result
    assert result["counts"]["applied"] == 1
    assert len(result["cleanup"]["removed"]) == 2
    properties = repository.submodels["urn:sm:chosen"]["submodelElements"]
    assert {p["idShort"]: p["value"] for p in properties} == {"Existing": "kept", "Communication_interfaces": "CAN / ModBus"}
    assert repository.submodels["urn:sm:unrelated"]["submodelElements"] == [prop("Unrelated")]


def test_population_api_removes_empty_collection_but_preserves_submodel(api):
    client, repository = api
    repository.submodels["urn:sm:other"]["submodelElements"] = [{
        "modelType": "SubmodelElementCollection", "idShort": "EmptyGroup", "value": [prop("Blank")],
    }]
    saved = root_plan(client)
    result = client.post("/api/populate", json={"filename": Path(saved["path"]).name,
                                               "aas_id_short": "urn:aas:chosen"}).json()
    assert result["success"], result
    assert repository.submodels["urn:sm:other"]["submodelElements"] == []
    assert {"submodel": "urn:sm:other", "path": "EmptyGroup",
            "modelType": "SubmodelElementCollection"} in result["cleanup"]["removed"]


@pytest.mark.parametrize("mode", ["dry-run", "failed-write"])
def test_population_dry_run_or_failed_write_never_removes_slots(api, monkeypatch, mode):
    client, repository = api
    saved = root_plan(client)
    if mode == "failed-write":
        monkeypatch.setattr(wizard_routes, "_apply_one", lambda *args: (_ for _ in ()).throw(RuntimeError("write failed")))
    response = client.post("/api/populate", json={"filename": Path(saved["path"]).name, "aas_id_short": "urn:aas:chosen", "dry_run": mode == "dry-run"})
    assert response.status_code == 200, response.text
    assert repository.deleted == []
    assert response.json()["cleanup"]["status"] in ("dry-run", "pending-writes")


def test_empty_submodel_is_a_selectable_canonical_root():
    root, = aas_routes._properties_of(sm())
    assert root["type"] == "Submodel" and root["apiPath"] == ""
    assert root["submodelId"] == "urn:sm:chosen" and root["semanticPath"] == "TechnicalData/"


def test_root_selection_roundtrips_and_rejects_foreign_submodel(api):
    client, repository = api
    saved = root_plan(client)
    result = client.get("/api/matching-results/" + Path(saved["path"]).name).json()
    row = result["results"][0]
    again = client.post("/api/save-matching-results", json={"filename": "again", "aas_id_short": "urn:aas:chosen", "results": [row]}).json()
    assert again["count"] == 1 and not again["unresolved"]
    row["aasProperties"] = [{"type": "Submodel", "apiPath": "", "submodelId": "urn:sm:unrelated"}]
    response = client.post("/api/save-matching-results", json={"filename": "foreign", "aas_id_short": "urn:aas:chosen", "results": [row]}).json()
    assert response["count"] == 0 and "does not belong" in response["unresolved"][0]["reason"]


def test_cli_population_uses_same_post_write_cleanup(tmp_path, monkeypatch):
    from a4s.aasctl import __main__ as cli
    repository = Repository([sm(elements=[prop("Blank"), prop("Zero", 0)])])
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"submodel": "urn:sm:chosen", "thresholds": {"high":1,"low":0}, "decisions": [{
        "entity": "Communication", "value": "CAN / ModBus", "unit": "", "source": "",
        "action": "create", "band": "manual", "reason": "reviewed", "path": "",
        "model_type": "Property", "id_short": "Communication", "value_type": "xs:string",
    }, {"entity": "Unmatched", "value": "unknown", "unit": "", "source": "",
        "action": "skip", "band": "none", "reason": "no home"}]}))
    monkeypatch.setattr(cli, "_client", lambda args: repository)
    class Out:
        def lines(self, payload, lines): self.payload = payload
    out = Out()
    cli.cmd_populate(argparse.Namespace(plan=str(path), skip_warnings=False, max_band="any", dry_run=False), out)
    assert len(out.payload["applied"]) == 1 and not out.payload["failed"]
    assert out.payload["cleanup"]["removed"] == [{"submodel": "urn:sm:chosen", "path": "Blank"}]


def test_cleanup_failures_are_reported_as_incomplete_without_losing_write_counts(api, monkeypatch):
    client, repository = api
    saved = root_plan(client)
    monkeypatch.setattr(repository, "delete_element", lambda *args: (_ for _ in ()).throw(RuntimeError("deletion failed")))
    result = client.post("/api/populate", json={"filename": Path(saved["path"]).name, "aas_id_short": "urn:aas:chosen"}).json()
    assert result["counts"] == {"applied": 1, "failed": 0, "notAttempted": 0, "total": 1}
    assert result["success"] is False and result["cleanup"]["status"] == "incomplete"
    assert len(result["cleanup"]["failed"]) == 2
