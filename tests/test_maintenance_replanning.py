from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from a4s.machines.festo_cp_lab import replanning as r


@pytest.mark.parametrize("event", [
    {"scheduled_at": "2026-10-07T08:00:00Z"},
    {"scheduled_at": "2026-10-07T08:00:00Z", "scheduled_end_at": "2026-10-07T08:00:00Z"},
    {"scheduled_at": "2026-10-07T08:00:00Z", "scheduled_end_at": "2026-10-07T07:00:00Z"},
    {"scheduled_at": "2026-10-07T08:00:00", "scheduled_end_at": "2026-10-07T09:00:00Z"},
])
def test_legacy_or_invalid_event_cannot_supply_an_assumed_end(event):
    with pytest.raises(ValueError):
        r.maintenance_interval(event)


def test_persisted_interval_cannot_be_overridden():
    with pytest.raises(ValueError, match="persisted"):
        r.maintenance_interval({"id": 3}, "2026-10-07T08:00:00Z", "2026-10-07T08:30:00Z")


@pytest.mark.parametrize("end", ["2026-10-07T08:30:00Z", "2026-10-08T00:15:00Z"])
@pytest.mark.parametrize("buffer_minutes", [0, 1440])
def test_pending_maintenance_immediately_delays_single_order_to_exact_end(monkeypatch, end, buffer_minutes):
    class Aas:
        def __init__(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_shell(self, asset):
            return {"submodels": [{"keys": [{"type": "Submodel", "value": "context"}]}]}
        def get_submodel(self, identifier):
            return {"idShort": "ProductionContext", "submodelElements": [{"idShort":"DemoProductionReleaseBufferMinutes","value":str(buffer_minutes)}]}
    class Mes:
        def __init__(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 10, 7, 7, 40, tzinfo=timezone.utc)
    orders = [{"id": i, "order_no": f"A4S-{i}", "line_id": 1, "status": "ACCEPTED",
               "planned_start_at": "2026-10-07T08:00:00Z", "planned_end_at": "2026-10-07T08:45:00Z"} for i in (1,)]
    maintenance = {"id": 3, "line_id": 1, "status": "pending", "scheduled_at": "2026-10-07T08:00:00Z", "scheduled_end_at": end}
    previews = []
    def execute(args, client):
        if args.command_name == "order show": return {"data": orders[int(args.target)-1]}
        if args.command_name == "maintenance show": return {"data": maintenance}
        assert args.command_name == "schedule move" and args.dry_run
        previews.append(args)
        return {"preflight": {"capacity": {"resources": [
            {"id": int(args.line_id), "cells": {args.planned_start_at[:10]: {"available_h": 8}}}]}}}
    monkeypatch.setattr(r, "BasyxClient", Aas)
    monkeypatch.setattr(r, "MesClient", Mes)
    monkeypatch.setattr(r.Config, "from_env", lambda: SimpleNamespace())
    monkeypatch.setattr(r, "resolve_line", lambda *args: {"id": 1, "code": "MAIN"})
    monkeypatch.setattr(r, "current_demo_orders", lambda *args: orders)
    monkeypatch.setattr(r, "execute", execute)
    monkeypatch.setattr(r, "datetime", Clock)
    result = r.proposal("asset", "http://localhost:8081", 3)
    assert len(previews) == 1
    affected, = result["placements"]
    assert affected["after"]["line_id"] == 1
    assert r.instant(affected["after"]["planned_start_at"]) == r.instant(end) + timedelta(minutes=buffer_minutes)
    assert (r.instant(affected["after"]["planned_end_at"]) - r.instant(affected["after"]["planned_start_at"])).total_seconds() == 45*60
    assert result["duration_minutes"] == (r.instant(end)-r.instant(maintenance["scheduled_at"])).total_seconds()/60


def test_skill_defers_duration_to_manual_and_uses_persisted_end():
    from pathlib import Path
    skill = Path("a4s/skills/fault-maintenance/SKILL.md").read_text(encoding="utf-8")
    assert "--scheduled-end-at END_ISO" in skill
    assert "persisted scheduled_end_at" in skill
    assert "a 60-minute MES reservation" not in skill
    assert "estimated duration from the applicable manual" in skill
