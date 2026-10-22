import copy
import os
import pytest
import json
import uuid

import httpx

from a4s.aasctl import model
from a4s.aasctl.client import BasyxClient, Endpoint

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.integration

backend = os.environ.get("A4S_UI_TEST_BACKEND", "http://localhost:8000")
target_endpoint = os.environ.get("A4S_UPDATE_TEST_ENDPOINT", "http://localhost:18081")
source_endpoint = os.environ.get("A4S_SOURCE_TEST_ENDPOINT", "http://localhost:8081")


def run(browser_name, directory):
    identity = "urn:a4s:browser-test:" + uuid.uuid4().hex
    sm_id = identity + ":nameplate"
    text = "Serial number: NEW456"
    text_hash = 0
    for char in text:
        text_hash = ((text_hash << 5) - text_hash + ord(char)) & 0xFFFFFFFF
    signed = text_hash if text_hash < 0x80000000 else text_hash - 0x100000000
    filename = f"text_input_{abs(signed):08x}.json"
    catalog_response = httpx.get(backend + '/api/templates')
    catalog_response.raise_for_status()
    template_id = next(row['id'] for row in catalog_response.json()
                       if row['name'] in ('Nameplate', 'DigitalNameplate'))
    with BasyxClient(Endpoint(source_endpoint)) as source:
        template = source.get_submodel(template_id)
    instance = model.make_submodel(sm_id, "DigitalNameplate")
    instance["semanticId"] = copy.deepcopy(template["semanticId"])
    instance["submodelElements"] = [
        model.make_element("Property", id_short="SerialNumber", value="OLD123")
    ]
    shell = model.make_shell(identity, "BrowserUpdateTest")
    shell["submodels"] = [
        {"type": "ModelReference", "keys": [{"type": "Submodel", "value": sm_id}]}
    ]
    with BasyxClient(Endpoint(target_endpoint)) as target:
        target.create_submodel(instance)
        target.create_shell(shell)
        try:
            response = httpx.post(
                backend + "/api/save-edited-entities",
                json={
                    "original_filename": filename,
                    "entities": [
                        {
                            "entity": "Serial number",
                            "value": "NEW456",
                            "description": "Product serial number",
                            "selected": True,
                        }
                    ],
                },
            )
            assert response.status_code == 200, response.text
            with sync_playwright() as p:
                browser = (
                    p.chromium.launch(channel="chrome", headless=True)
                    if browser_name == "chrome"
                    else p.firefox.launch(headless=True)
                )
                context = browser.new_context(viewport={"width": 1700, "height": 900})
                seed = {
                    "currentStep": 0,
                    "highestVisitedStep": 0,
                    "wizardData": {
                        "viewMode": "wizard",
                        "mode": "edit",
                        "submodelTemplate": [],
                        "aasServerEndpoint": target_endpoint,
                        "aasUIEndpoint": "http://localhost:3000",
                        "targetAAS": identity,
                        "dataSourceType": "text",
                        "dataSourceValue": text,
                        "uploadedFiles": [],
                        "extractedEntities": [],
                        "isExtracting": False,
                        "editedEntitiesFile": None,
                        "extractionConfigurations": [],
                        "chosenConfiguration": "",
                        "extractionWarnings": [],
                        "matchedProperties": [],
                        "isMatching": False,
                        "isGenerating": False,
                        "generationComplete": False,
                        "pendingAgentQuestion": "",
                        "assets": [],
                        "connections": [],
                    },
                }
                context.add_init_script(
                    '''window.WebSocket = class {
                      static CONNECTING=0;static OPEN=1;static CLOSING=2;static CLOSED=3;
                      readyState=0;addEventListener(){}removeEventListener(){}send(){}close(){}
                    };localStorage.setItem("wizard",''' + json.dumps(json.dumps(seed)) + ");"
                )
                page = context.new_page()
                page.on("dialog", lambda d: (_ for _ in ()).throw(AssertionError(d.message)))
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(os.environ["A4S_UI_TEST_URL"])
                page.get_by_role("button", name="Shop floor & AAS", exact=True).click()
                inventory = page.get_by_role("list", name="Existing submodels")
                inventory.wait_for(timeout=30000)
                assert "DigitalNameplate" in inventory.inner_text()
                assert page.get_by_text("Compare the four actions", exact=True).count() == 0
                assert page.get_by_label("SM instance to update", exact=True).count() == 0
                assert page.get_by_text("CollectionofSMTs", exact=False).count() == 0
                page.get_by_role("button", name="Create New AAS", exact=True).click()
                page.locator(".standardized-templates input[type=checkbox]").first.wait_for(timeout=30000)
                assert page.locator(".standardized-templates input[type=checkbox]").count() > 0
                assert page.locator("#targetAAS").input_value() == ""
                page.get_by_role("button", name="Edit Existing AAS", exact=True).click()
                page.locator(f'input[name="targetAAS"][value="{identity}"]').check(timeout=30000)
                inventory.wait_for(timeout=30000)
                page.locator(".standardized-templates input[type=checkbox]").evaluate_all(
                    '(nodes,id)=>nodes.find(node=>node.value===id).click()', template_id
                )
                assert page.locator(".connection-settings").get_attribute("open") is None
                page.screenshot(
                    path=str(directory / f"{browser_name}-automatic-input.png"), full_page=True
                )
                next_button = page.locator(".wizard-actions button").last
                next_button.scroll_into_view_if_needed()
                next_button.click()
                page.get_by_text("Entity Extraction", exact=False).first.wait_for(
                    timeout=10000
                ) if page.get_by_text("Entity Extraction", exact=False).count() else None
                page.locator(".wizard-actions button").last.click()
                page.locator(".matching-stage").wait_for(state="visible", timeout=120000)
                page.wait_for_function(
                    "!document.querySelector('.wizard-actions button:last-child').disabled",
                    timeout=120000,
                )
                rows = page.locator(".matching-stage tbody tr")
                old_row = rows.filter(has_text="OLD123")
                new_row = rows.filter(has_text="NEW456")
                old_row.wait_for()
                assert old_row.locator(".input-origin").count() == 0
                assert new_row.locator(".input-origin").count() == 0
                assert "line-through" not in old_row.locator("td").first.evaluate(
                    "node => getComputedStyle(node).textDecorationLine"
                )
                assert not old_row.locator("input[type=checkbox]").is_checked()
                assert not new_row.locator("input[type=checkbox]").is_checked()
                old_row.locator("input[type=checkbox]").check()
                new_row.locator("input[type=checkbox]").check()
                assert not old_row.locator("input[type=checkbox]").is_checked()
                page.screenshot(
                    path=str(directory / f"{browser_name}-conflict-review.png"), full_page=True
                )
                assert target.get_submodel(sm_id)["submodelElements"][0]["value"] == "OLD123"
                page.locator(".wizard-actions button").last.click()
                page.get_by_text("AAS populated successfully", exact=True).wait_for(timeout=30000)
                details = page.locator(".population-change-details")
                assert details.get_attribute("open") is None
                details.locator("summary").first.click()
                page.get_by_text("Show changes and previous values", exact=True).click()
                assert page.locator(".update-review").get_by_text("OLD123", exact=False).count()
                page.screenshot(path=str(directory / f"{browser_name}-review.png"), full_page=True)
                current_refs = [
                    ref["keys"][0]["value"] for ref in target.get_shell(identity)["submodels"]
                ]
                assert len(current_refs) == 1 and current_refs[0] != sm_id
                assert target.get_submodel(sm_id)["submodelElements"][0]["value"] == "OLD123"
                actual = {
                    node["idShort"]: node.get("value")
                    for node in target.get_submodel(current_refs[0])["submodelElements"]
                }
                assert actual["SerialNumber"] == "NEW456", actual
                assert not errors, errors
                page.screenshot(
                    path=str(directory / f"{browser_name}-completed.png"), full_page=True
                )
                print(browser_name, "PASS", flush=True)
                browser.close()
        finally:
            created_ids = {
                ref["keys"][0]["value"] for ref in target.get_shell(identity).get("submodels", [])
            } | {sm_id}
            target.delete_shell(identity)
            for created_id in created_ids:
                if created_id.startswith(identity):
                    target.delete_submodel(created_id)


def test_review_and_commit_through_firefox(tmp_path):
    if not os.environ.get("A4S_UI_TEST_URL"):
        pytest.skip("Set A4S_UI_TEST_URL to the local frontend")
    run("firefox", tmp_path)
