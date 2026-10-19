import json

import httpx
import pytest

from a4s.mesctl.client import Config, MesClient, MesError
from a4s.mesctl.commands import build_parser, command_info
from a4s.mesctl.executor import execute

SLOT = " --scheduled-at 2026-10-07T09:00:00+02:00 --scheduled-end-at 2026-10-07T09:30:00+02:00"
CREATE = "maintenance create --title Review --event-type corrective --line 7" + SLOT


def run(words, handler):
    with MesClient(
        Config("http://mes.test", "secret"), transport=httpx.MockTransport(handler)
    ) as client:
        return execute(build_parser().parse_args(words.split()), client)


def test_create_readback_and_classification():
    body = {}

    def handler(req):
        if req.method == "POST":
            assert req.url.path == "/api/v1/maintenance-events"
            body.update(json.loads(req.content))
            return httpx.Response(201, json={"data": {"id": 9}})
        assert req.url.path == "/api/v1/maintenance-events/9"
        return httpx.Response(200, json={"data": {**body, "id": 9, "status": "PENDING"}})

    result = run(CREATE, handler)
    assert result["verified"]
    assert body["line_id"] == 7
    assert command_info("mes " + CREATE)[
        "mutates"
    ]
    assert not command_info(
        "mes " + CREATE + " --dry-run"
    )["mutates"]


def test_dry_run_and_required_mes_target():
    def no_http(req):
        pytest.fail("Unexpected HTTP")

    result = run(
        CREATE + " --dry-run", no_http
    )
    assert result["dry_run"]
    with pytest.raises(MesError, match="Select a MES"):
        run("maintenance create --title Review --event-type corrective" + SLOT + " --dry-run", no_http)


@pytest.mark.parametrize(
    "verb,status", [("start", "IN_PROGRESS"), ("complete", "COMPLETED"), ("cancel", "CANCELLED")]
)
def test_transitions_are_read_back(verb, status):
    written = False

    def handler(req):
        nonlocal written
        if req.method == "POST":
            written = True
            return httpx.Response(200, json={"data": {"id": 9}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": 9,
                    "status": status if written else "PENDING",
                    "resolution_notes": "Reviewed",
                }
            },
        )

    result = run(
        f"maintenance {verb} 9" + (" --resolution-notes Reviewed" if verb == "complete" else ""),
        handler,
    )
    assert result["verified"]


def test_write_verification_failure_is_not_replayed():
    writes = []

    def handler(req):
        if req.method == "POST":
            writes.append(req)
            return httpx.Response(201, json={"data": {"id": 9}})
        return httpx.Response(
            200, json={"data": {"id": 9, "title": "different", "status": "PENDING"}}
        )

    result = run(CREATE, handler)
    assert not result["verified"] and len(writes) == 1


@pytest.mark.parametrize("start,end", [
    ("2026-10-07T09:00:00Z", "2026-10-07T09:00:00Z"),
    ("2026-10-07T09:00:00Z", "2026-10-07T08:30:00Z"),
    ("2026-10-07T09:00:00", "2026-10-07T09:30:00Z"),
    ("2026-10-07T09:00:00Z", "2026-10-07T09:30:00"),
])
def test_invalid_interval_never_writes(start, end):
    with pytest.raises(MesError):
        run(f"maintenance create --title Review --event-type corrective --line 7 --scheduled-at {start} --scheduled-end-at {end}",
            lambda req: pytest.fail("Invalid interval must be rejected before HTTP"))


def test_create_requires_both_timestamps_even_for_preview():
    for suffix in ("", " --scheduled-at 2026-10-07T09:00:00Z"):
        with pytest.raises(SystemExit):
            build_parser().parse_args(("maintenance create --title Review --event-type corrective --line 7 --dry-run" + suffix).split())


def test_end_timestamp_is_normalized_and_verified_as_an_instant():
    body = {}
    def handler(req):
        if req.method == "POST":
            body.update(json.loads(req.content))
            assert body["scheduled_at"] == "2026-10-07T09:00:00+02:00"
            assert body["scheduled_end_at"] == "2026-10-07T09:30:00+02:00"
            return httpx.Response(201, json={"data": {"id": 9}})
        return httpx.Response(200, json={"data": {**body, "id": 9, "status": "pending",
            "scheduled_at": "2026-10-07T07:00:00Z", "scheduled_end_at": "2026-10-07T07:30:00Z"}})
    with MesClient(Config("http://mes.test", "secret", server_timezone="Europe/Berlin"), transport=httpx.MockTransport(handler)) as client:
        result = execute(build_parser().parse_args(CREATE.split()), client)
    assert result["verified"]


def test_api_discarding_end_is_unverified_without_replay():
    writes = []
    body = {}
    def handler(req):
        if req.method == "POST":
            writes.append(req)
            body.update(json.loads(req.content))
            return httpx.Response(201, json={"data": {"id": 9}})
        return httpx.Response(200, json={"data": {**body, "id": 9, "status": "pending", "scheduled_end_at": None}})
    result = run(CREATE, handler)
    assert not result["verified"] and len(writes) == 1


def test_update_one_bound_checks_persisted_other_bound():
    calls = []
    def handler(req):
        calls.append(req.method)
        assert req.method == "GET"
        return httpx.Response(200, json={"data": {"id": 9,
            "scheduled_at": "2026-10-07T07:00:00Z", "scheduled_end_at": "2026-10-07T07:30:00Z"}})
    with pytest.raises(MesError, match="end after start"):
        run("maintenance update 9 --scheduled-at 2026-10-07T08:00:00Z", handler)
    assert calls == ["GET"]
