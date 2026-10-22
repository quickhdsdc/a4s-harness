"""Behavior through the update module's public prepare/review/commit/history interface."""

import copy

import pytest

from a4s.aasctl import updates
from a4s.aasctl.client import AasHttpError
from a4s.aasctl.match import Decision


def prop(name, value=None):
    return {"modelType": "Property", "idShort": name, "valueType": "xs:string", "value": value}


def ref(identifier):
    return {"type": "ModelReference", "keys": [{"type": "Submodel", "value": identifier}]}


class Repository:
    def __init__(self):
        self.shells = {
            "urn:device": {
                "id": "urn:device",
                "idShort": "Device",
                "modelType": "AssetAdministrationShell",
                "assetInformation": {"assetKind": "Instance"},
                "submodels": [ref("urn:plate")],
            }
        }
        self.models = {
            "urn:plate": {
                "id": "urn:plate",
                "idShort": "Nameplate",
                "modelType": "Submodel",
                "kind": "Instance",
                "submodelElements": [
                    prop("Manufacturer", "Verified manufacturer"),
                    prop("Custom", "Keep me"),
                ],
            }
        }
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_shell(self, key):
        return copy.deepcopy(self.shells[key])

    def list_shells(self, **kwargs):
        return copy.deepcopy(list(self.shells.values()))

    def get_submodel(self, key):
        if key not in self.models:
            raise AasHttpError(404, "http://repo/submodels", "missing")
        return copy.deepcopy(self.models[key])

    def list_submodel_refs(self, key):
        return self.get_shell(key)["submodels"]

    def list_concept_descriptions(self):
        return []

    def replace_submodel(self, key, value):
        self.models[key] = copy.deepcopy(value)
        self.writes.append(("replace", key))

    def create_submodel(self, value):
        assert value["id"] not in self.models
        self.models[value["id"]] = copy.deepcopy(value)
        self.writes.append(("create", value["id"]))

    def add_submodel_ref(self, key, value):
        self.shells[key]["submodels"].append(copy.deepcopy(value))
        self.writes.append(("attach", key))

    def remove_submodel_ref(self, key, value):
        self.shells[key]["submodels"] = [
            r for r in self.shells[key]["submodels"] if r["keys"][0]["value"] != value
        ]
        self.writes.append(("detach", key))


@pytest.fixture
def scenario(tmp_path):
    target, source = Repository(), Repository()
    source.models = {
        "urn:template": {
            "id": "urn:template",
            "idShort": "Nameplate",
            "modelType": "Submodel",
            "kind": "Template",
            "administration": {"version": "2", "revision": "0"},
            "submodelElements": [
                prop("Manufacturer", "EXAMPLE must never overwrite"),
                prop("SerialNumber"),
                {
                    "modelType": "SubmodelElementCollection",
                    "idShort": "EmptyGroup",
                    "value": [prop("Blank")],
                },
                {"modelType": "MultiLanguageProperty", "idShort": "Description", "value": []},
            ],
        }
    }
    return updates.Store(tmp_path / "history.sqlite3"), target, source


def prepared(scenario, mode="enrich"):
    store, target, source = scenario
    return updates.prepare(
        store,
        target,
        "http://target",
        "urn:device",
        [{"templateId": "urn:template", "targetId": "urn:plate", "mode": mode}],
        source,
        "http://templates",
    )


def decision(path="SerialNumber", value="SN123", model_type="Property"):
    return Decision(
        entity="Serial number",
        value=value,
        unit="",
        source="datasheet.pdf p1",
        action="write",
        band="manual",
        reason="reviewed",
        path=path,
        model_type=model_type,
        value_type="xs:string",
    )


def test_mixed_actions_share_review_but_only_write_their_own_targets(scenario):
    store, target, source = scenario
    selections = []
    for index, mode in enumerate(("enrich", "migrate", "replace", "add")):
        template_id = f"urn:template:{index}"
        source.models[template_id] = copy.deepcopy(source.models["urn:template"])
        source.models[template_id]["id"] = template_id
        source.models[template_id]["idShort"] = f"Template{index}"
        target_id = ""
        if mode != "add":
            target_id = f"urn:existing:{index}"
            target.models[target_id] = copy.deepcopy(target.models["urn:plate"])
            target.models[target_id]["id"] = target_id
            target.models[target_id]["idShort"] = f"Instance{index}"
            target.shells["urn:device"]["submodels"].append(ref(target_id))
        selections.append({"templateId": template_id, "targetId": target_id, "mode": mode})
    # Unselected SM must not even undergo empty-element cleanup.
    target.models["urn:plate"]["submodelElements"].append(prop("Blank"))
    untouched = copy.deepcopy(target.models["urn:plate"])
    draft = updates.prepare(
        store, target, "http://target", "urn:device", selections, source, "http://templates"
    )
    candidate_ids = {row["id"] for row in updates.candidate_client(draft).list_submodels()}
    assert len(candidate_ids) == 4 and "urn:plate" not in candidate_ids
    assert [row["mode"] for row in draft["selections"]] == ["enrich", "migrate", "replace", "add"]
    reviewed = updates.review(store, draft["id"], [(key, decision()) for key in candidate_ids])
    assert not target.writes and not source.writes
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["result"]["counts"] == {"applied": 4, "failed": 0, "notAttempted": 0, "total": 4}
    attached = {row["keys"][0]["value"] for row in target.shells["urn:device"]["submodels"]}
    assert attached == candidate_ids | {"urn:plate"}
    assert "urn:existing:2" not in attached  # Replacement detaches only its old instance.
    assert target.models["urn:plate"] == untouched


def test_no_template_selection_uses_all_existing_sms_without_adding_an_instance(scenario):
    store, target, source = scenario
    target.models["urn:other"] = {
        "id": "urn:other",
        "idShort": "Other",
        "modelType": "Submodel",
        "kind": "Instance",
        "submodelElements": [prop("SerialNumber"), prop("Blank")],
    }
    target.shells["urn:device"]["submodels"].append(ref("urn:other"))
    shell_before = copy.deepcopy(target.shells["urn:device"])
    draft = updates.prepare(
        store, target, "http://target", "urn:device", [], source, "http://templates"
    )
    assert set(draft["activeIds"]) == {"urn:plate", "urn:other"}
    reviewed = updates.review(store, draft["id"], [("urn:other", decision())])
    assert "Blank" in {row["path"] for row in reviewed["cleanup"]["removed"]}
    updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert target.shells["urn:device"] == shell_before
    assert not any(operation in {"create", "attach", "detach"} for operation, _ in target.writes)
    assert {row["idShort"] for row in target.models["urn:other"]["submodelElements"]} == {
        "SerialNumber"
    }


def test_two_actions_cannot_target_the_same_existing_sm(scenario):
    store, target, source = scenario
    with pytest.raises(updates.UpdateError, match="only have one update intent"):
        updates.prepare(
            store,
            target,
            "http://target",
            "urn:device",
            [
                {"templateId": "urn:template", "targetId": "urn:plate", "mode": mode}
                for mode in ("enrich", "replace")
            ],
            source,
            "http://templates",
        )
    assert not target.writes and not source.writes


def test_enrichment_restores_pruned_template_slots_without_touching_live_data(scenario):
    store, target, source = scenario
    before = copy.deepcopy(target.models)
    draft = prepared(scenario)
    client = updates.candidate_client(draft)
    rows = {p["idShort"]: p for p in client.get_submodel("urn:plate")["submodelElements"]}
    assert rows["Manufacturer"]["value"] == "Verified manufacturer"
    assert "SerialNumber" in rows and rows["Custom"]["value"] == "Keep me"
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    assert target.models == before and target.writes == []
    assert {r["path"] for r in reviewed["cleanup"]["omitted"]} >= {"EmptyGroup", "EmptyGroup.Blank"}
    assert reviewed["cleanup"]["removed"] == []
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["result"]["counts"] == {"applied": 1, "failed": 0, "notAttempted": 0, "total": 1}
    assert {p["idShort"]: p["value"] for p in target.models["urn:plate"]["submodelElements"]} == {
        "Manufacturer": "Verified manufacturer",
        "Custom": "Keep me",
        "SerialNumber": "SN123",
    }
    assert (
        source.models["urn:template"]["submodelElements"][0]["value"]
        == "EXAMPLE must never overwrite"
    )
    assert store.history("http://target", "urn:device")[0]["status"] == "committed"
    assert store.history("http://other", "urn:device") == []


def test_reviewed_value_changes_and_translations_preserve_other_languages(scenario):
    store, target, _ = scenario
    target.models["urn:plate"]["submodelElements"].append(
        {
            "modelType": "MultiLanguageProperty",
            "idShort": "Description",
            "value": [{"language": "de", "text": "Original"}],
        }
    )
    draft = prepared(scenario)
    reviewed = updates.review(
        store,
        draft["id"],
        [("urn:plate", decision("Description", "New description", "MultiLanguageProperty"))],
    )
    value = next(
        p["value"]
        for p in reviewed["reviewed"]["submodels"]["urn:plate"]["submodelElements"]
        if p["idShort"] == "Description"
    )
    assert {p["language"]: p["text"] for p in value} == {"de": "Original", "en": "New description"}


def test_concurrent_external_change_prevents_all_writes(scenario):
    store, target, _ = scenario
    draft = prepared(scenario)
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    target.models["urn:plate"]["submodelElements"][0]["value"] = "Changed by SLM"
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["status"] == "conflicted" and target.writes == []
    assert not result["result"]["success"]


def test_commit_retry_is_idempotent_and_old_review_cannot_be_used(scenario):
    store, target, _ = scenario
    draft = prepared(scenario)
    first = updates.review(store, draft["id"], [("urn:plate", decision(value="SN1"))])
    second = updates.review(store, draft["id"], [("urn:plate", decision(value="SN2"))])
    with pytest.raises(updates.Conflict):
        updates.commit(store, draft["id"], first["reviewHash"], target)
    result = updates.commit(store, draft["id"], second["reviewHash"], target)
    count = len(target.writes)
    assert (
        updates.commit(store, draft["id"], second["reviewHash"], target)["result"]
        == result["result"]
    )
    assert len(target.writes) == count


def test_replacement_archives_old_state_and_reviewed_restore_rebinds_it(scenario):
    store, target, _ = scenario
    old = copy.deepcopy(target.models["urn:plate"])
    draft = prepared(scenario, "replace")
    new_id = draft["activeIds"][0]
    reviewed = updates.review(store, draft["id"], [(new_id, decision())])
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["status"] == "committed"
    assert updates.refs(target.shells["urn:device"]) == [new_id]
    assert target.models["urn:plate"] == old
    restoration = updates.restore(store, draft["id"], target)
    assert updates.refs(target.shells["urn:device"]) == [new_id]  # restore is a preview
    restored = updates.commit(store, restoration["id"], restoration["reviewHash"], target)
    assert restored["status"] == "committed", restored["result"]
    assert updates.refs(target.shells["urn:device"]) == ["urn:plate"]


def test_shared_live_submodel_requires_replacement(scenario):
    store, target, _ = scenario
    target.shells["urn:other"] = {**copy.deepcopy(target.shells["urn:device"]), "id": "urn:other"}
    draft = prepared(scenario)
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["status"] == "conflicted" and target.writes == []


def test_pinned_release_survives_same_id_overwrite_in_template_repository(scenario):
    store, target, source = scenario
    release = store.release("http://templates", source.models["urn:template"])
    source.models["urn:template"]["submodelElements"] = [prop("Different")]
    draft = updates.prepare(
        store,
        target,
        "http://target",
        "urn:device",
        [
            {
                "mode": "migrate",
                "targetId": "urn:plate",
                "templateId": "urn:template",
                "releaseHash": release["hash"],
            }
        ],
        source,
        "http://templates",
    )
    assert "SerialNumber" in {
        p["idShort"] for p in draft["candidate"]["submodels"]["urn:plate"]["submodelElements"]
    }
    assert draft["selections"][0]["release"]["hash"] == release["hash"]


def test_partial_network_failure_is_journaled_and_cannot_be_blindly_retried(scenario, monkeypatch):
    store, target, _ = scenario
    draft = prepared(scenario, "replace")
    reviewed = updates.review(store, draft["id"], [(draft["activeIds"][0], decision())])
    monkeypatch.setattr(
        target, "add_submodel_ref", lambda *a: (_ for _ in ()).throw(RuntimeError("network down"))
    )
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["status"] == "partial" and result["journal"][0]["operation"] == "write-submodel"
    assert not result["result"]["success"] and result["result"]["counts"]["applied"] == 0
    with pytest.raises(updates.Conflict):
        updates.commit(store, draft["id"], reviewed["reviewHash"], target)


def test_migration_preserves_entity_identity_and_relationship_annotations(scenario):
    store, target, source = scenario
    entity = {
        "modelType": "Entity",
        "idShort": "Component",
        "entityType": "SelfManagedEntity",
        "globalAssetId": "urn:component:123",
        "statements": [prop("Manufacturer", "Real")],
    }
    annotation = {
        "modelType": "AnnotatedRelationshipElement",
        "idShort": "Link",
        "first": ref("urn:one"),
        "second": ref("urn:two"),
        "annotations": [prop("Evidence", "Measured")],
    }
    target.models["urn:plate"]["submodelElements"] += [entity, annotation]
    empty_entity = copy.deepcopy(entity)
    empty_entity.pop("globalAssetId")
    empty_entity["statements"] = []
    empty_annotation = copy.deepcopy(annotation)
    empty_annotation["annotations"] = []
    source.models["urn:template"]["submodelElements"] += [empty_entity, empty_annotation]
    draft = prepared(scenario, "migrate")
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    nodes = {
        p["idShort"]: p for p in reviewed["reviewed"]["submodels"]["urn:plate"]["submodelElements"]
    }
    assert nodes["Component"] == entity
    assert nodes["Link"] == annotation


def test_review_includes_schema_metadata_changes(scenario):
    _, target, _ = scenario
    before = updates.snapshot(target, "urn:device")
    after = copy.deepcopy(before)
    after["submodels"]["urn:plate"]["semanticId"] = {
        "type": "ExternalReference",
        "keys": [{"type": "GlobalReference", "value": "urn:new"}],
    }
    after["submodels"]["urn:plate"]["submodelElements"][0]["valueType"] = "xs:integer"
    changes = updates.difference(before, after)
    assert {row["path"] for row in changes if row["action"] == "schema-update"} == {
        "",
        "Manufacturer",
    }


def test_wrong_list_item_type_is_rejected_before_any_repository_mutation(scenario):
    store, target, source = scenario
    source.models["urn:template"]["submodelElements"].append(
        {
            "modelType": "SubmodelElementList",
            "idShort": "Readings",
            "typeValueListElement": "Range",
            "valueTypeListElement": "xs:double",
            "value": [],
        }
    )
    draft = prepared(scenario)
    item = decision("Readings", "12")
    item.action = "create"
    item.id_short = None
    with pytest.raises(updates.UpdateError, match="type does not match"):
        updates.review(store, draft["id"], [("urn:plate", item)])
    assert not target.writes


def test_late_review_cannot_overwrite_a_committed_revision(scenario):
    import threading

    store, target, _ = scenario
    draft = prepared(scenario)
    first = updates.review(store, draft["id"], [("urn:plate", decision())])
    read = threading.Event()
    proceed = threading.Event()

    class PausedStore(updates.Store):
        def get(self, identifier):
            value = super().get(identifier)
            read.set()
            assert proceed.wait(5)
            return value

    errors = []

    def stale_review():
        try:
            updates.review(
                PausedStore(store.path), draft["id"], [("urn:plate", decision(value="Different"))]
            )
        except updates.Conflict as exc:
            errors.append(exc)

    thread = threading.Thread(target=stale_review)
    thread.start()
    assert read.wait(5)
    committed = updates.commit(store, draft["id"], first["reviewHash"], target)
    proceed.set()
    thread.join(5)
    assert errors and store.get(draft["id"])["status"] == "committed"
    assert store.get(draft["id"])["journal"] == committed["journal"]


def test_lost_write_response_is_reconciled_and_has_reviewed_recovery(scenario, monkeypatch):
    store, target, _ = scenario
    draft = prepared(scenario)
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    replace = target.replace_submodel

    def lost_response(key, model):
        replace(key, model)
        raise RuntimeError("response lost after server accepted write")

    monkeypatch.setattr(target, "replace_submodel", lost_response)
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["status"] == "partial"
    assert result["result"]["counts"]["applied"] == 1
    assert result["journal"][0]["status"] == "pending"
    restored = updates.restore(store, draft["id"], target)
    assert restored["status"] == "reviewed"


def test_semantic_hash_tolerates_optional_null_but_keeps_list_order():
    assert updates.digest({"value": None}) == updates.digest({})
    assert updates.digest({"value": [1, 2]}) != updates.digest({"value": [2, 1]})


def test_empty_submodel_list_readback_can_omit_value_but_nonempty_list_is_strict():
    empty = {'modelType': 'SubmodelElementList', 'idShort': 'Guidelines',
             'typeValueListElement': 'Property', 'valueTypeListElement': 'xs:string'}
    assert updates.digest(dict(empty, value=[])) == updates.digest(dict(empty, value=None))
    assert updates.digest(dict(empty, value=[])) == updates.digest(empty)
    first = {'modelType': 'Property', 'valueType': 'xs:string', 'value': 'first'}
    second = {'modelType': 'Property', 'valueType': 'xs:string', 'value': 'second'}
    assert updates.digest(dict(empty, value=[first])) != updates.digest(empty)
    assert updates.digest(dict(empty, value=[first, second])) != updates.digest(dict(empty, value=[second, first]))


def test_reconcile_interrupted_worker_observes_results_without_repeating_writes(scenario):
    store, target, _ = scenario
    draft = prepared(scenario)
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    applying = store.claim(draft["id"], reviewed["reviewHash"])
    target.replace_submodel("urn:plate", applying["reviewed"]["submodels"]["urn:plate"])
    previous_count = len(target.writes)
    result = updates.reconcile(store, draft["id"], target)
    assert result["status"] == "committed"
    assert result["result"]["counts"]["applied"] == 1
    assert len(target.writes) == previous_count


def test_unfilled_new_file_does_not_introduce_an_empty_collection(scenario):
    store, _, source = scenario
    source.models["urn:template"]["submodelElements"].append(
        {
            "modelType": "SubmodelElementCollection",
            "idShort": "Files",
            "value": [
                {
                    "modelType": "File",
                    "idShort": "Manual",
                    "contentType": "application/pdf",
                    "value": None,
                }
            ],
        }
    )
    draft = prepared(scenario)
    reviewed = updates.review(store, draft["id"], [("urn:plate", decision())])
    assert "Files" not in {
        row["idShort"] for row in reviewed["reviewed"]["submodels"]["urn:plate"]["submodelElements"]
    }


def test_migration_refuses_to_relabel_values_with_a_different_unit(scenario):
    _, target, source = scenario
    target.models["urn:plate"]["submodelElements"][0]["qualifiers"] = [
        {"type": "Unit", "valueType": "xs:string", "value": "mm"}
    ]
    source.models["urn:template"]["submodelElements"][0]["qualifiers"] = [
        {"type": "Unit", "valueType": "xs:string", "value": "m"}
    ]
    draft = prepared(scenario, "migrate")
    assert draft["conflicts"][0]["path"] == "Manufacturer"
