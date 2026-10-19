"""Actual PDF extraction and synthetic fault controls, without external services."""

import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from a4s.machines.festo_cp_lab import pdf_knowledge, knowledge, demo_monitor
from a4s.server import festo_demo_routes as routes


@pytest.fixture(autouse=True)
def pdf_dependency():
    pytest.importorskip("pypdfium2")


def test_rehearsal_actions_require_closed_issue_and_correct_order_state(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException

    monkeypatch.setattr(routes.Config, "from_env", lambda: SimpleNamespace(server_timezone="UTC"))
    state = {"context": {"MESLineCode": "A4S-FESTO"},
             "line": {"id": 1}, "order": {"id": 5, "status": "PENDING"},
             "issues": [{"id": 9, "status": "OPEN"}]}
    for retired in ("return_upcoming", "move_upcoming"):
        with pytest.raises(HTTPException) as exc:
            routes.action_words(retired, state)
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        routes.action_words("accept_affected", state)
    assert exc.value.status_code == 409
    state["issues"][0]["status"] = "CLOSED"
    assert routes.action_words("accept_affected", state) == ["order", "accept", "5"]
    state["order"]["status"] = "ACCEPTED"
    with pytest.raises(HTTPException):
        routes.action_words("accept_affected", state)


def test_pdf_corpus_has_page_citations_and_real_file_hashes():
    rows = pdf_knowledge.chunks()
    assert len(rows) == 12
    assert len({r["id"] for r in rows}) == 12
    assert {r["origin"] for r in rows} == {"REFERENCE", "DEMO_FICTION", "PROJECT_CONTRACT", "ENGINEERING_SCENARIO", "FIELD_OBSERVATION"}
    for row in rows:
        data = pdf_knowledge.document_path(row["document_id"]).read_bytes()
        assert data.startswith(b"%PDF-")
        assert row["sha256"] == hashlib.sha256(data).hexdigest()
        assert f"p. {row['page']}" in row["citation"]
        assert "CONTENT" not in row["text"]
    assert sum(d["pages"] for d in pdf_knowledge.catalog()) == 12


def test_workpiece_field_retrieval_preserves_normal_cycle_and_alarm_limits():
    rows = knowledge.search("BG8 xGM_BG8 Werkstueck workpiece", limit=4)
    field = next(row for row in rows if row["id"] == "bg8-workpiece-trigger-evidence")
    assert field["origin"] == "FIELD_OBSERVATION"
    assert "false value alone must not trigger" in field["text"]
    assert "polarity and auxiliary logic are unverified" in field["text"]
    assert field["filename"] == "Festo-Fault-and-Maintenance-Manual.pdf"
    assert field['page'] == 5
    assert '67 times each' in field['text'] and '73 times each' in field['text']
    assert '16:44:51.567' in field['text'] and '16:44:55.441' in field['text']


def test_fault_manual_tables_are_retrievable_with_validation_and_level_fields():
    manual = [row for row in pdf_knowledge.chunks() if row["document_id"] == "fault-manual"]
    assert len(manual) == 6
    physical = next(row for row in manual if row["id"] == "physical-alarm-catalogue")
    assert "Handling / level" in physical["text"]
    assert "M1" in physical["text"] and "M3" in physical["text"]
    assert "manufacturer meaning unverified" in physical["text"]
    assert "Busy=false" in physical["text"]
    hits = knowledge.search("iRetCode code 7 no workpiece", 4)
    assert any(hit["id"] == "physical-workpiece-code-evidence" for hit in hits)


def test_duration_manual_is_english_and_retrievable_through_ui_api():
    manual = [row for row in pdf_knowledge.chunks() if row["document_id"] == "fault-manual"]
    import re
    assert all(not re.search(r"[\u3400-\u9fff]", row["text"] + row["title"] + row["filename"]) for row in manual)
    duration = next(row for row in manual if row["id"] == "maintenance-duration-planning")
    assert "15 minutes" in duration["text"] and "30 minutes" in duration["text"]
    assert "No measured maintenance durations" in duration["text"]
    assert "scheduled_end_at" in duration["text"]
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        catalog = client.get("/api/demo/festo/knowledge/documents").json()["documents"]
        assert next(row for row in catalog if row["id"] == "fault-manual")["pages"] == 6
        result = client.get("/api/demo/festo/knowledge", params={"query": "maintenance duration planning estimate"}).json()
        assert any(row["id"] == "maintenance-duration-planning" for row in result["chunks"])
        assert client.get("/api/demo/festo/knowledge/documents/fault-manual").content.startswith(b"%PDF-")


def test_retrieval_reads_modified_pdf_not_authoring_constants(monkeypatch, tmp_path):
    for identifier, filename in pdf_knowledge.FILES.items():
        data = pdf_knowledge.document_path(identifier).read_bytes()
        if identifier == "fault-manual":
            # Equal-byte-length edit keeps the PDF xref intact while proving
            # text and provenance are derived from the file actually ingested.
            assert b"6.0" in data
            data = data.replace(b"6.0", b"9.9")
        (tmp_path / filename).write_bytes(data)
    monkeypatch.setattr(pdf_knowledge, "DIRECTORY", tmp_path)
    row = next(r for r in knowledge.search("pressure leakage", 7) if r["id"] == "simulation-alarm-catalogue")
    assert "9.9 bar" in row["text"]
    assert "6.0 bar" not in row["text"]
    assert row["sha256"] == hashlib.sha256((tmp_path / row["filename"]).read_bytes()).hexdigest()


def test_missing_pdf_fails_without_silent_text_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_knowledge, "DIRECTORY", tmp_path)
    with pytest.raises(FileNotFoundError, match="PDFs missing"):
        knowledge.search("pressure")
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.get("/api/demo/festo/knowledge").status_code == 503
        assert client.get("/api/demo/festo/knowledge/documents").status_code == 503


def test_pdf_http_catalog_download_and_unknown_id():
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        catalog = client.get("/api/demo/festo/knowledge/documents")
        assert catalog.status_code == 200 and len(catalog.json()["documents"]) == 3
        assert {r['id'] for r in catalog.json()['documents']} == {'technical', 'production', 'fault-manual'}
        for retired in ('maintenance', 'fault-service', 'workpiece-field'):
            assert client.get('/api/demo/festo/knowledge/documents/' + retired).status_code == 404
        pdf = client.get("/api/demo/festo/knowledge/documents/technical")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        assert pdf.headers["content-type"] == "application/pdf"
        assert client.get("/api/demo/festo/knowledge/documents/not-allowed").status_code == 404
        result = client.get("/api/demo/festo/knowledge", params={"query": "pressure leakage"}).json()
        assert result["retrieval"].startswith("PDF")
        assert all("page" in c and "sha256" in c for c in result["chunks"])


def test_historical_simulation_is_available_only_when_explicitly_requested():
    query = 'pneumatic pressure ramp leakage'
    assert all(row['id'] != 'pneumatic-leak-scenario' for row in knowledge.search(query, 20))
    legacy = next(row for row in knowledge.search(query, 20, include_history=True)
                  if row['id'] == 'pneumatic-leak-scenario')
    assert legacy['retrieval_scope'] == 'HISTORICAL_ONLY'
    assert '0.13 bar' in legacy['text'] and 'Historical HTTP generator only' in legacy['text']
    current = next(row for row in knowledge.search('UI OPC fault leak pressure flow', 4)
                   if row['id'] == 'simulation-alarm-catalogue')
    assert 'immediately' in current['text']
    assert '6.0 bar and 12 litres/minute' in current['text']


def test_maintenance_levels_are_defined_once_and_corpus_is_english():
    import re
    rows = pdf_knowledge.chunks()
    assert sum('Project maintenance levels: M0' in row['text'] for row in rows) == 1
    assert all(not re.search(r'[\u3400-\u9fff]', row['text'] + row['title'] + row['filename'] + row['source']) for row in rows)
    assert {path.name for path in pdf_knowledge.DIRECTORY.glob('*.pdf')} == set(pdf_knowledge.FILES.values())


def test_operator_injects_and_recovers_without_rewriting_signal_history(monkeypatch):
    monkeypatch.setattr(demo_monitor, "STATE", {"run_id": None, "started_at": None, "active": False})
    now = [100.0]
    monkeypatch.setattr(demo_monitor.time, "time", lambda: now[0])
    with pytest.raises(ValueError, match="Start simulation"):
        demo_monitor.inject()
    demo_monitor.start(normal_only=True)
    now[0] += 50
    assert demo_monitor.observe()["status"] == "NORMAL"
    demo_monitor.inject()
    now[0] += 25
    alarm = demo_monitor.observe()
    assert alarm["status"] == "FAULT"
    assert demo_monitor.inject()["alarm_id"] == alarm["alarm_id"]
    recovered = demo_monitor.recover()
    assert recovered["status"] == "NORMAL" and recovered["alarm_id"] is None
    assert any(r["status"] == "FAULT" for r in recovered["history"])
    demo_monitor.inject()
    now[0] += 25
    assert demo_monitor.observe()["alarm_id"] != alarm["alarm_id"]


def test_new_signal_controls_require_explicit_simulation(monkeypatch):
    monkeypatch.setattr(demo_monitor, "STATE", {"run_id": None, "started_at": None, "active": False})
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        for action in ("inject", "recover"):
            assert client.post(f"/api/demo/festo/monitor/{action}", json={"mode": "LIVE"}).status_code == 422
        assert client.post("/api/demo/festo/monitor/inject", json={"mode": "SIMULATION"}).status_code == 409
        state = client.post("/api/demo/festo/monitor/start", json={"mode": "SIMULATION", "normal_only": True}).json()
        assert state["active"] and state["leak_started_at"] is None
