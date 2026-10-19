"""Exercise one approval across real adapter preflight, writes and read-back."""
import copy
from datetime import datetime, timedelta, timezone
import json
import shlex

import httpx
import pytest

from a4s.kernel.approval import BUSINESS, READ, Decision, Gate, Policy, Scopes, classify
from a4s.machines.festo_cp_lab import replanning
from a4s.mesctl import recovery
from a4s.mesctl.client import Config, MesClient, MesError
from a4s.mesctl.commands import build_parser, command_info
from a4s.mesctl.execution import ExecutionContext
from a4s.mesctl.executor import execute


@pytest.fixture
def world(monkeypatch, tmp_path):
    now = datetime(2026, 10, 7, 8, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return now
    monkeypatch.setenv("A4S_HOME", str(tmp_path))
    monkeypatch.setattr(recovery, "clock", lambda: now)
    monkeypatch.setattr(replanning, "datetime", Clock)
    context = {"MESBaseUrl": "http://mes.test", "MESLineCode": "MAIN", "MESBackupLineCode": "BACKUP",
               "ReplanningPolicy": "compatible backup; affected line after maintenance"}
    monkeypatch.setattr(replanning, "production_context", lambda *a: copy.deepcopy(context))
    state = {"orders": {i: {"id": i, "order_no": f"A4S-demo-{s}", "line_id": 1,
                 "status": "ACCEPTED", "product_type_id": 3, "planned_qty": 90, "produced_quantity": 0,
                 "planned_start_at": "2026-10-07T07:00:00Z", "planned_end_at": "2026-10-07T07:45:00Z"}
               for i, s in [(24, "A")]},
             "maintenance": {}, "changes": [], "writes": [], "omit_end": False, "fail_second": False,
             "capacity": 8, "context": context}
    def handle(req):
        path = req.url.path
        if req.method != "GET":
            state["writes"].append((req.method, path))
            fields = json.loads(req.content)
            if path == "/api/v1/maintenance-events":
                event = {"id": 9, "status": "pending", **fields}
                if state["omit_end"]: event.pop("scheduled_end_at")
                state["maintenance"][9] = event
                return httpx.Response(200, json={"data": event})
            order_id = int(path.rsplit("/", 1)[-1])
            if state["fail_second"] and order_id == 24:
                raise httpx.ReadTimeout("uncertain commit", request=req)
            state["orders"][order_id].update(fields)
            state["changes"].append({"id": order_id, "work_order_id": order_id, "after": fields})
            return httpx.Response(200, json={"data": state["orders"][order_id]})
        if path == "/api/v1/lines": data = [{"id": 1, "code": "MAIN"}, {"id": 2, "code": "BACKUP"}]
        elif path == "/api/v1/work-orders": data = list(state["orders"].values())
        elif path.startswith("/api/v1/work-orders/"): data = state["orders"][int(path.rsplit("/", 1)[-1])]
        elif path.endswith("/product-types"): data = [{"id": 3}]
        elif path.endswith("/workstations"): data = []
        elif path == "/api/v1/schedule/capacity":
            data = {"resources": [{"id": i, "cells": {day: {"available_h": state["capacity"]} for day in ("2026-10-07", "2026-10-08", "2026-10-09")}} for i in (1, 2)]}
            return httpx.Response(200, json=data)
        elif path == "/api/v1/schedule/changes": data = state["changes"]
        elif path == "/api/v1/maintenance-events": data = list(state["maintenance"].values())
        elif path.startswith("/api/v1/maintenance-events/"): data = state["maintenance"][int(path.rsplit("/", 1)[-1])]
        else: pytest.fail(f"Unexpected request {req.method} {path}")
        return httpx.Response(200, json={"data": data})
    with MesClient(Config("http://mes.test", "secret", server_timezone="Europe/Berlin"),
                   transport=httpx.MockTransport(handle)) as client:
        yield state, client, ExecutionContext("fault-event", "recovery-attempt"), now


def prepared(world, *, existing=False):
    state, client, ctx, now = world
    flags = ["--maintenance-id", "9"] if existing else ["--title", "Inspection", "--description", "Manual p4. fault-event",
              "--start", "2026-10-07T10:30:00+02:00", "--end", "2026-10-07T11:00:00+02:00"]
    args = build_parser().parse_args(["recovery", "prepare", "--asset", "asset", "--aas-endpoint", "http://aas.test", *flags])
    return execute(args, client, context=ctx)


def apply(plan, world):
    _, client, ctx, _ = world
    return execute(build_parser().parse_args(shlex.split(plan["apply_command"])[1:]), client, context=ctx)


def test_one_approval_creates_maintenance_and_moves_both_existing_orders(world):
    state, client, ctx, _ = world
    plan = prepared(world)
    assert not state["writes"]
    approvals = []
    def approve(request):
        approvals.append(request)
        return Decision(True, "combined exact plan approved", "operator")
    gate = Gate(policy=Policy(), approver=approve)
    command = plan["apply_command"]
    assert classify("shell", {"command": command}).risk == BUSINESS
    assert gate.check("shell", {"command": command}).allowed
    assert "automatic production rescheduling" in approvals[0].question
    assert "24" in approvals[0].question
    result = apply(plan, world)
    assert len(approvals) == 1 and result["verified"]
    assert len(state["writes"]) == 2
    assert state["orders"][24]["line_id"] == 1
    assert recovery.instant(state["orders"][24]["planned_start_at"]) == recovery.instant(state["maintenance"][9]["scheduled_end_at"])
    assert state["maintenance"][9]["status"] == "pending"
    assert len(result["schedule_changes"]["data"]) == 1
    assert len({s["execution"]["execution_id"] for s in result["steps"]}) == 2
    with pytest.raises(ValueError, match="already attempted"):
        apply(plan, world)
    assert len(state["writes"]) == 2


def test_missing_persisted_end_stops_all_order_moves(world):
    state, _, _, _ = world
    plan = prepared(world)
    state["omit_end"] = True
    result = apply(plan, world)
    assert not result["verified"] and not result["order_moves"]
    assert len(state["writes"]) == 1
    assert "not verified" in result["error"]


def test_partial_move_timeout_records_progress_and_cannot_be_replayed(world):
    state, _, _, _ = world
    plan = prepared(world)
    state["fail_second"] = True
    result = apply(plan, world)
    assert not result["verified"] and result["maintenance_id"] == 9
    assert [m["order_id"] for m in result["order_moves"]] == []
    assert result["failure_execution"]["outcome"] == "unknown"
    with pytest.raises(ValueError, match="already attempted"):
        apply(plan, world)
    assert len(state["writes"]) == 2


@pytest.mark.parametrize("change", ["order", "quantity", "reset", "binding", "capacity", "insufficient", "destination", "duplicate"])
def test_changed_business_state_stops_before_any_write(world, change):
    state, client, _, _ = world
    plan = prepared(world)
    if change == "order": state["orders"][24]["status"] = "IN_PROGRESS"
    if change == "quantity": state["orders"][24]["planned_qty"] = 100
    if change == "reset":
        state["orders"][26] = {**state["orders"].pop(24), "id": 26}
    if change == "binding": state["context"]["MESLineCode"] = "CHANGED"
    if change == "capacity": state["capacity"] = 0
    if change == "insufficient": state["capacity"] = .25
    if change == "destination": client.config.endpoint = "http://other.test"
    if change == "duplicate": state["maintenance"][10] = {"id": 10, "line_id": 1, "description": "fault-event"}
    with pytest.raises(MesError): apply(plan, world)
    assert not state["writes"]


def test_expired_or_tampered_plan_is_refused_before_approval(world, monkeypatch):
    _, _, _, now = world
    plan = prepared(world)
    monkeypatch.setattr(recovery, "clock", lambda: now + timedelta(minutes=11))
    gate = Gate(policy=Policy(), approver=lambda r: pytest.fail("Expired plan must not ask"))
    assert not gate.check("shell", {"command": plan["apply_command"]}).allowed
    monkeypatch.setattr(recovery, "clock", lambda: now)
    path = recovery.directory() / (plan["plan_id"] + ".json")
    obj = json.loads(path.read_text())
    obj["placements"][0]["after"]["line_id"] = 99
    path.write_text(json.dumps(obj))
    assert not gate.check("shell", {"command": plan["apply_command"]}).allowed


def test_subresource_scope_and_deny_list_cannot_be_bypassed(world):
    plan = prepared(world)
    gate = Gate(policy=Policy(deny=["mes://work-orders/24"]), approver=lambda r: pytest.fail("Deny must win"))
    assert not gate.check("shell", {"command": plan["apply_command"]}).allowed
    gate = Gate(policy=Policy(), scopes=Scopes(entries={"worker": ["mes://maintenance-events*", "mes://work-orders/24"]}, configured=True),
                actor="worker", approver=lambda r: pytest.fail("Outside scope must not ask"))
    assert not gate.check("shell", {"command": plan["apply_command"]}).allowed


def test_existing_event_is_reused_with_one_approval_and_no_duplicate(world):
    state, _, _, _ = world
    state["maintenance"][9] = {"id": 9, "line_id": 1, "status": "pending", "title": "Inspection",
                              "scheduled_at": "2026-10-07T10:30:00+02:00", "scheduled_end_at": "2026-10-07T11:00:00+02:00"}
    plan = prepared(world, existing=True)
    result = apply(plan, world)
    assert result["verified"] and result["maintenance_id"] == 9
    assert len(state["writes"]) == 1
    assert all(method == "PUT" for method, _ in state["writes"])


def test_default_workflow_and_pdf_describe_the_same_combined_approval():
    from pathlib import Path
    from a4s.machines.festo_cp_lab.knowledge_sources import PRODUCTION_DOCUMENTS
    skill = Path("a4s/skills/fault-maintenance/SKILL.md").read_text(encoding="utf-8")
    assert "mes recovery prepare" in skill and "gate asks ONCE" in skill
    assert "separate approval" not in skill
    assert "automatically execute" in PRODUCTION_DOCUMENTS[1]["text"]
    assert command_info("mes recovery prepare --asset a --aas-endpoint http://a --maintenance-id 9")["mutates"] is False


def test_every_write_in_combined_plan_has_its_own_ledger_record(world, tmp_path):
    from a4s.environments.base import ExecResult
    from a4s.ledger import Ledger
    from a4s.tools import ToolRegistry
    state, client, _, _ = world
    plan = prepared(world)
    class Environment:
        def run(self, command, **kw):
            ctx = ExecutionContext(kw["env"]["A4S_MES_TRACE_ID"], kw["env"]["A4S_MES_EXECUTION_ID"])
            result = execute(build_parser().parse_args(shlex.split(command)[1:]), client, context=ctx)
            return ExecResult(0, json.dumps(result), "", False, 0, "test")
    ledger = Ledger(tmp_path / "ledger.db", "chat-session", actor="web-chat")
    try:
        requests = []
        def approve(req):
            requests.append(req)
            return Decision(True, "approved combined plan", "operator")
        registry = ToolRegistry(Environment(), ledger, tmp_path, gate=Gate(Policy(), ledger, approve))
        result = json.loads(registry.dispatch("shell", {"command": plan["apply_command"]}))
        assert result["verified"] and len(requests) == 1
        events = list(ledger.read(session_id="chat-session", limit=100))
        children = [e for e in events if e.kind == "mes.write" and e.payload.get("mutation")]
        assert {e.subject for e in children} == {"mes://maintenance-events/9", "mes://work-orders/24"}
        assert all(e.payload["verified"] and e.payload["read_back"] for e in children)
    finally:
        ledger.close()


def test_elapsed_slots_are_replanned_on_whole_minutes_not_microseconds(world, monkeypatch):
    now = datetime(2026, 10, 7, 8, 0, 12, 123456, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return now
    monkeypatch.setattr(replanning, "datetime", Clock)
    plan = prepared(world)
    begin = recovery.instant(plan["placements"][0]["after"]["planned_start_at"])
    assert begin >= now + timedelta(minutes=10)
    assert begin.second == 0 and begin.microsecond == 0


def test_capacity_dates_follow_mes_timezone_across_utc_midnight():
    begin, end = recovery.instant("2026-10-07T22:00:00Z"), recovery.instant("2026-10-07T22:45:00Z")
    preview = {"body": {"planned_start_at": "2026-10-08T00:00:00+02:00", "planned_end_at": "2026-10-08T00:45:00+02:00"},
               "preflight": {"capacity": {"resources": [{"id": 1, "cells": {"2026-10-08": {"available_h": 8}}}]}}}
    assert replanning.available_capacity(preview, 1, begin, end) == 8


def test_demo_two_hour_window_creates_pending_event_and_immediately_postpones_order(world):
    state, _, _, _ = world
    state["context"]["DemoMaintenanceWindowMinutes"] = "120"
    plan = prepared(world)
    assert plan["duration_minutes"] == 120
    assert recovery.instant(plan["maintenance_end"]) == recovery.instant("2026-10-07T12:30:00+02:00")
    assert not state["writes"]
    result = apply(plan, world)
    assert result["verified"]
    assert state["maintenance"][9]["status"] == "pending"
    assert len(state["writes"]) == 2
    assert recovery.instant(state["orders"][24]["planned_start_at"]) == recovery.instant(plan["maintenance_end"])
    assert recovery.instant(state["orders"][24]["planned_end_at"]) == recovery.instant("2026-10-07T13:15:00+02:00")


def test_demo_reservation_never_overrides_an_existing_persisted_maintenance_end(world):
    state, _, _, _ = world
    state["context"]["DemoMaintenanceWindowMinutes"] = "120"
    state["maintenance"][9] = {"id":9,"line_id":1,"status":"pending",
        "scheduled_at":"2026-10-07T10:30:00+02:00","scheduled_end_at":"2026-10-07T11:00:00+02:00"}
    plan = prepared(world, existing=True)
    assert plan["duration_minutes"] == 30
    assert recovery.instant(plan["maintenance_end"]) == recovery.instant(state["maintenance"][9]["scheduled_end_at"])


def test_demo_next_day_three_hours_and_one_day_production_allowance(world):
    state, _, _, _ = world
    state["context"].update(DemoMaintenanceWindowMinutes="180",
        DemoMaintenanceStartDayOffset="1", DemoProductionReleaseBufferMinutes="1440")
    plan = prepared(world)
    assert recovery.instant(plan["maintenance_start"]).date().isoformat() == "2026-10-08"
    assert plan["duration_minutes"] == 180
    end = recovery.instant(plan["maintenance_end"])
    assert recovery.instant(plan["placements"][0]["after"]["planned_start_at"]) == end + timedelta(days=1)
    assert not state["writes"]
    result = apply(plan, world)
    assert result["verified"]
    assert state["maintenance"][9]["status"] == "pending"
    assert recovery.instant(state["orders"][24]["planned_start_at"]) == end + timedelta(days=1)
    assert recovery.instant(state["orders"][24]["planned_end_at"]) == end + timedelta(days=1,minutes=45)
