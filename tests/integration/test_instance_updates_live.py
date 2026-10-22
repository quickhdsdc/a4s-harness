"""Real V3 REST, read-back, persistence and history; synthetic resources only."""

import os
import uuid

import pytest

from a4s.aasctl import model, updates
from a4s.aasctl.client import BasyxClient, Endpoint
from a4s.aasctl.match import Decision

pytestmark = pytest.mark.integration


def test_live_add_enrich_replace_and_restore_without_touching_templates(tmp_path):
    endpoint = os.environ.get("A4S_UPDATE_TEST_ENDPOINT")
    if not endpoint:
        pytest.skip("Set A4S_UPDATE_TEST_ENDPOINT to an isolated repository")
    identifier = "urn:a4s:update-test:" + uuid.uuid4().hex
    store = updates.Store(tmp_path / "updates.sqlite3")
    ids = []
    with BasyxClient(Endpoint(endpoint)) as client:
        shell = model.make_shell(identifier, "UpdateTest")
        client.create_shell(shell)
        template = model.make_submodel(identifier + ":template", "Nameplate", kind="Template")
        template["administration"] = {"version": "2", "revision": "0"}
        template["submodelElements"] = [
            model.make_element("Property", id_short="Manufacturer", value="Example"),
            model.make_element("Property", id_short="SerialNumber"),
        ]
        client.create_submodel(template)
        ids.append(template["id"])
        original = client.get_submodel(template["id"])
        try:
            draft = updates.prepare(
                store,
                client,
                endpoint,
                identifier,
                [{"templateId": template["id"], "mode": "add"}],
                client,
                endpoint,
            )
            sm_id = draft["activeIds"][0]
            ids.append(sm_id)
            decision = Decision(
                entity="Serial number",
                value="SN123",
                unit="",
                source="test input",
                action="write",
                band="manual",
                reason="reviewed",
                path="SerialNumber",
                model_type="Property",
                value_type="xs:string",
            )
            review = updates.review(store, draft["id"], [(sm_id, decision)])
            result = updates.commit(store, draft["id"], review["reviewHash"], client)
            assert result["status"] == "committed", result["result"]
            assert client.get_submodel(sm_id)["idShort"] == "Nameplate"
            assert client.get_submodel(template["id"]) == original
            retry = updates.commit(store, draft["id"], review["reviewHash"], client)
            assert retry["result"] == result["result"]
            draft = updates.prepare(
                store,
                client,
                endpoint,
                identifier,
                [{"templateId": template["id"], "mode": "enrich", "targetId": sm_id}],
                client,
                endpoint,
            )
            decision.path = "Manufacturer"
            decision.entity = "Manufacturer"
            decision.value = "Real manufacturer"
            review = updates.review(store, draft["id"], [(sm_id, decision)])
            result = updates.commit(store, draft["id"], review["reviewHash"], client)
            assert result["status"] == "committed", result["result"]
            actual = {
                p["idShort"]: p.get("value") for p in client.get_submodel(sm_id)["submodelElements"]
            }
            assert actual == {"Manufacturer": "Real manufacturer", "SerialNumber": "SN123"}
            draft = updates.prepare(
                store,
                client,
                endpoint,
                identifier,
                [{"templateId": template["id"], "mode": "replace", "targetId": sm_id}],
                client,
                endpoint,
            )
            new_id = draft["activeIds"][0]
            ids.append(new_id)
            review = updates.review(store, draft["id"], [(new_id, decision)])
            result = updates.commit(store, draft["id"], review["reviewHash"], client)
            assert result["status"] == "committed", result["result"]
            restore = updates.restore(store, draft["id"], client)
            result = updates.commit(store, restore["id"], restore["reviewHash"], client)
            assert result["status"] == "committed", result["result"]
            assert updates.refs(client.get_shell(identifier)) == [sm_id]
            assert len(store.history(endpoint, identifier)) == 4
        finally:
            client.delete_shell(identifier)
            for key in reversed(ids):
                client.delete_submodel(key)
