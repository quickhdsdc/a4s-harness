"""Maintenance Events, not Issues or AAS maintenance instructions."""

import argparse
from datetime import datetime
import math

from ..arguments import positive_id
from ..client import MesError
from .scheduling import schedule_time


def cost(raw):
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("Cost must be finite and non-negative")
    return value


def prepare(client, fields, target_id):
    for key in ("scheduled_at", "scheduled_end_at"):
        if key not in fields:
            continue
        try:
            if datetime.fromisoformat(fields[key].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
            fields[key] = schedule_time(fields[key], client.config.server_timezone)
        except (ValueError, TypeError):
            raise MesError(f"{key} requires an ISO timestamp with timezone offset") from None
    if "currency" in fields and not 1 <= len(fields["currency"]) <= 10:
        raise MesError("Currency must contain 1-10 characters")
    event = client.get(f"/api/v1/maintenance-events/{target_id}") if target_id else None
    if not target_id and not any(fields.get(k) for k in ("line_id", "workstation_id", "tool_id")):
        raise MesError("Select a MES line, workstation or tool; an AAS ID is not a MES resource ID")
    if not target_id or any(k in fields for k in ("scheduled_at", "scheduled_end_at")):
        current = (event or {}).get("data", {})
        try:
            start, end = (datetime.fromisoformat(
                fields.get(k, current.get(k)).replace("Z", "+00:00")
            ) for k in ("scheduled_at", "scheduled_end_at"))
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise MesError("Maintenance requires a timezone-aware start and end with end after start") from None
    return {"event": event} if event else {}


def register(cmd, opt):
    root = "/api/v1/maintenance-events"
    statuses = ("PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    p = cmd(
        "maintenance ls",
        root,
        "List Maintenance Events (not Issues)",
        resource="maintenance-events",
    )
    opt(p, "line", "line_id")
    opt(p, "tool-id", type=positive_id)
    opt(p, "status", choices=statuses)
    opt(p, "from")
    opt(p, "to")
    opt(p, "page", type=positive_id)
    opt(p, "per-page", type=int, choices=range(1, 101))
    cmd(
        "maintenance show",
        root + "/{id}",
        "Read Maintenance Event",
        resource="maintenance-events",
        target=True,
    )
    for verb, method in (("create", "POST"), ("update", "PATCH")):
        p = cmd(
            "maintenance " + verb,
            root + ("/{id}" if verb == "update" else ""),
            "Write Maintenance Event; does not repair equipment or hold an order",
            method,
            "maintenance-events",
            target=verb == "update",
            prepare=prepare,
            expected_status="PENDING" if verb == "create" else None,
            verify_fields=True,
            effects=(
                "Writes a maintenance business record; no PLC or implicit order/schedule change.",
            ),
        )
        opt(p, "title", required=verb == "create")
        opt(
            p,
            "event-type",
            choices=("planned", "corrective", "inspection"),
            required=verb == "create",
        )
        opt(p, "line", "line_id")
        for flag in ("workstation-id", "tool-id", "cost-source-id", "assigned-to-id"):
            opt(p, flag, type=positive_id)
        for flag in ("scheduled-at", "scheduled-end-at"):
            opt(p, flag, required=verb == "create", help="ISO timestamp with timezone offset; end must follow start")
        for flag in ("description", "currency"):
            opt(p, flag)
        opt(p, "actual-cost", type=cost)
        if verb == "update":
            opt(p, "resolution-notes")
    for verb, status in (
        ("start", "IN_PROGRESS"),
        ("complete", "COMPLETED"),
        ("cancel", "CANCELLED"),
    ):
        p = cmd(
            "maintenance " + verb,
            root + "/{id}/" + verb,
            "Advance Maintenance Event lifecycle",
            "POST",
            "maintenance-events",
            target=True,
            prepare=prepare,
            expected_status=status,
            verify_fields=True,
            effects=(
                "Changes the MES maintenance record only; physical recovery is not verified.",
            ),
        )
        if verb == "complete":
            opt(p, "resolution-notes", required=True)
            opt(p, "actual-cost", type=cost)
            opt(p, "currency")
