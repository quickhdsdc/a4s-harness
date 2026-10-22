"""User-facing automatic update policy through prepare, matching and commit."""

import copy

import pytest

from a4s.aasctl import automatic_updates as automatic, updates
from a4s.aasctl.match import Decision, Entity
from test_instance_updates import Repository, prop, ref


def fixture_categories(templates, existing):
    """Offline model double; production calls the batch LLM classifier."""
    groups = [{'templateId': t['id'], 'replaces': [key for key, model in existing.items()
               if automatic.same_family(t, model)], 'reason': 'Fixture category decision'} for t in templates]
    used = {key for group in groups for key in group['replaces']}
    return {'method': 'fixture', 'replacements': groups,
            'retainedIds': [key for key in existing if key not in used]}


@pytest.fixture(autouse=True)
def offline_category_model(monkeypatch):
    monkeypatch.setattr(automatic, 'classify_categories', fixture_categories)


def prepared(tmp_path):
    target, source = Repository(), Repository()
    source.models = {
        "urn:template:v2": {
            "id": "urn:template:v2",
            "idShort": "Nameplate",
            "modelType": "Submodel",
            "kind": "Template",
            "administration": {"version": "2"},
            "semanticId": {
                "type": "ExternalReference",
                "keys": [
                    {"type": "GlobalReference", "value": "https://standard/nameplate/2/0/Nameplate"}
                ],
            },
            "submodelElements": [prop("Manufacturer"), prop("SerialNumber")],
        }
    }
    target.models["urn:plate"]["semanticId"] = {
        "type": "ExternalReference",
        "keys": [{"type": "GlobalReference", "value": "https://standard/nameplate/1/0/Nameplate"}],
    }
    target.models["urn:plate"]["submodelElements"].append(prop("SerialNumber", "OLD123"))
    target.models["urn:other"] = {
        "id": "urn:other",
        "idShort": "TechnicalData",
        "modelType": "Submodel",
        "kind": "Instance",
        "submodelElements": [prop("Voltage", "24")],
    }
    target.shells["urn:device"]["submodels"].append(ref("urn:other"))
    store = updates.Store(tmp_path / "history.sqlite3")
    draft = automatic.prepare(
        store,
        target,
        "http://target",
        "urn:device",
        ["urn:template:v2"],
        source,
        "http://templates",
    )
    return store, target, source, draft


def test_selected_category_is_replaced_only_in_the_candidate_and_others_stay_matchable(tmp_path):
    store, target, source, draft = prepared(tmp_path)
    assert not target.writes and not source.writes
    candidate = updates.candidate_client(draft)
    assert "urn:plate" not in {row["id"] for row in candidate.list_submodels()}
    assert "urn:other" in {row["id"] for row in candidate.list_submodels()}
    assert draft["replacementGroups"][0]["replaces"] == ["urn:plate"]
    facts = automatic.matching_inputs(draft, [Entity("Serial number", "NEW456", source="pdf p1")])
    assert {row.value for row in facts} >= {"NEW456", "OLD123", "Verified manufacturer", "Keep me"}
    new_id = draft["replacementGroups"][0]["candidateId"]
    # Matching decisions for both the new template and an unrelated retained SM.
    reviewed = updates.review(
        store,
        draft["id"],
        [
            (
                new_id,
                Decision(
                    "Serial number",
                    "NEW456",
                    "",
                    "pdf p1",
                    "write",
                    "manual",
                    "reviewed",
                    path="SerialNumber",
                    model_type="Property",
                ),
            ),
            (
                "urn:other",
                Decision(
                    "Voltage",
                    "48",
                    "",
                    "pdf p2",
                    "write",
                    "manual",
                    "reviewed",
                    path="Voltage",
                    model_type="Property",
                ),
            ),
        ],
    )
    assert target.models["urn:plate"]["submodelElements"][-1]["value"] == "OLD123"
    result = updates.commit(store, draft["id"], reviewed["reviewHash"], target)
    assert result["status"] == "committed"
    assert set(updates.refs(target.shells["urn:device"])) == {new_id, "urn:other"}
    assert target.models["urn:other"]["submodelElements"][0]["value"] == "48"
    assert "urn:plate" in target.models  # Archive/shared users retain the old resource.


def test_same_name_with_different_declared_meaning_is_not_replaced():
    one = {
        "id": "urn:one",
        "idShort": "TechnicalData",
        "semanticId": {"keys": [{"value": "urn:machine"}]},
    }
    other = {"idShort": "TechnicalData", "semanticId": {"keys": [{"value": "urn:battery"}]}}
    assert not automatic.same_family(one, other)
    assert automatic.same_family(one, {"idShort": "TechnicalData"})


def test_llm_category_decision_replaces_different_legacy_ids_and_carries_values(tmp_path, monkeypatch):
    store, target, source, _ = prepared(tmp_path)
    old = target.models['urn:plate']
    old['idShort'] = 'TechnicalData_IMM'
    old['semanticId'] = {'keys': [{'value': 'urn:legacy:technical-data'}]}
    template = source.models['urn:template:v2']
    template['idShort'] = 'TechnicalDataIMM'
    template['semanticId'] = {'keys': [{'value': 'urn:new:machine-data'}]}
    assert not automatic.same_family(template, old)
    calls = []
    def classify(templates, existing):
        calls.append((templates, existing))
        return {'method': 'llm-batch', 'replacements': [
            {'templateId': template['id'], 'replaces': ['urn:plate'], 'reason': 'Same machine technical category'}],
            'retainedIds': ['urn:other']}
    monkeypatch.setattr(automatic, 'classify_categories', classify)
    result = automatic.prepare(store, target, 'http://target', 'urn:device',
                               [template['id']], source, 'http://source')
    assert len(calls) == 1
    assert 'urn:plate' not in result['candidate']['submodels']
    assert 'urn:other' in result['candidate']['submodels']
    assert result['replacementGroups'][0]['replaces'] == ['urn:plate']
    assert any(fact['value'] == 'OLD123' for fact in result['legacyInputs'])
    assert result['categoryAssessment']['method'] == 'llm-batch'
    assert not target.writes and not source.writes


def test_versioned_samm_and_template_origin_identify_the_family():
    one = {
        "id": "https://standards/templates/Nameplate/2/0",
        "semanticId": {"keys": [{"value": "urn:samm:example:2.0.0#Nameplate"}]},
    }
    assert automatic.same_family(
        one, {"semanticId": {"keys": [{"value": "urn:samm:example:1.0.0#Nameplate"}]}}
    )
    assert automatic.same_family(
        one, {"administration": {"templateId": "https://standards/templates/Nameplate/1/0"}}
    )


def test_duplicate_old_instances_are_combined_and_two_selected_versions_are_rejected(tmp_path):
    store, target, source, _ = prepared(tmp_path)
    target.models["urn:plate:duplicate"] = copy.deepcopy(target.models["urn:plate"])
    target.models["urn:plate:duplicate"]["id"] = "urn:plate:duplicate"
    target.shells["urn:device"]["submodels"].append(ref("urn:plate:duplicate"))
    draft = automatic.prepare(
        store,
        target,
        "http://target",
        "urn:device",
        ["urn:template:v2"],
        source,
        "http://templates",
    )
    assert set(draft["replacementGroups"][0]["replaces"]) == {"urn:plate", "urn:plate:duplicate"}
    source.models["urn:template:v3"] = copy.deepcopy(source.models["urn:template:v2"])
    source.models["urn:template:v3"]["id"] = "urn:template:v3"
    with pytest.raises(updates.UpdateError, match="one template version"):
        automatic.prepare(
            store,
            target,
            "http://target",
            "urn:device",
            ["urn:template:v2", "urn:template:v3"],
            source,
            "http://templates",
        )
    assert not target.writes


def test_no_selected_templates_keeps_all_existing_matching_destinations(tmp_path):
    store, target, source, _ = prepared(tmp_path)
    draft = automatic.prepare(
        store, target, "http://target", "urn:device", [], source, "http://templates"
    )
    assert set(draft["activeIds"]) == set(target.models)
    assert not draft["legacyInputs"] and not draft["replacementGroups"]


def test_review_distinguishes_old_and_new_conflicts_but_merges_equal_values(tmp_path):
    _, _, _, draft = prepared(tmp_path)
    old = next(row for row in draft["legacyInputs"] if row["entity"] == "SerialNumber")
    base = {
        "action": "write",
        "submodelId": "urn:new",
        "apiPath": "SerialNumber",
        "aasType": "Property",
        "unit": "",
        "selected": True,
    }
    rows = automatic.review_rows(
        draft,
        [
            dict(base, source="pdf p1", extractedValue="NEW456"),
            dict(base, source=old["source"], extractedValue="OLD123"),
        ],
    )
    assert len(rows) == 2 and all(row["valueConflict"] and not row["selected"] for row in rows)
    assert {row["inputOrigin"] for row in rows} == {"Existing data", "New input"}
    rows = automatic.review_rows(
        draft,
        [
            dict(base, source="pdf p1", extractedValue="OLD123"),
            dict(base, source=old["source"], extractedValue="OLD123"),
        ],
    )
    assert len(rows) == 1 and rows[0]["inputOrigin"] == "Existing data + new input"
    assert rows[0]["source"] == old["source"]


def test_existing_localized_values_keep_all_languages_on_review(tmp_path):
    store, target, source, _ = prepared(tmp_path)
    localized = {
        "modelType": "MultiLanguageProperty",
        "idShort": "Manufacturer",
        "value": [{"language": "en", "text": "Company"}, {"language": "de", "text": "Firma"}],
    }
    target.models["urn:plate"]["submodelElements"] = [localized]
    source.models["urn:template:v2"]["submodelElements"] = [dict(localized, value=[])]
    draft = automatic.prepare(
        store,
        target,
        "http://target",
        "urn:device",
        ["urn:template:v2"],
        source,
        "http://templates",
    )
    fact = draft["legacyInputs"][0]
    reviewed = updates.review(
        store,
        draft["id"],
        [
            (
                draft["replacementGroups"][0]["candidateId"],
                Decision(
                    fact["entity"],
                    fact["value"],
                    "",
                    fact["source"],
                    "write",
                    "manual",
                    "reviewed",
                    path="Manufacturer",
                    model_type="MultiLanguageProperty",
                ),
            )
        ],
    )
    new_id = draft["replacementGroups"][0]["candidateId"]
    assert (
        reviewed["reviewed"]["submodels"][new_id]["submodelElements"][0]["value"]
        == localized["value"]
    )
