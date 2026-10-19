"""Local immutable coordination plans; OpenMES remains the business authority.

A plan is a single approval unit containing exact requests, not permission for
the model to invent later moves. Sequential writes are not a MES transaction.
Any uncertain or partial attempt is retained and must be inspected, not replayed.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .client import MesError
from .execution import ExecutionContext


def clock():
    return datetime.now(timezone.utc)


def directory():
    return Path(os.getenv("A4S_HOME", Path.home() / ".a4s")).expanduser() / "recovery-plans"


def digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(plan_id):
    if not re.fullmatch(r"[a-f0-9]{64}", plan_id):
        raise ValueError("Use the exact plan ID returned by mes recovery prepare")
    try:
        plan = json.loads((directory() / (plan_id + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Prepared recovery plan was not found or is unreadable") from None
    if digest(plan) != plan_id:
        raise ValueError("Prepared recovery plan changed; prepare a new plan")
    validate_plan(plan)
    if (directory() / (plan_id + ".used")).exists():
        raise ValueError("Recovery plan already attempted; inspect its results, do not replay it")
    if clock() >= instant(plan["expires_at"]):
        raise ValueError("Recovery plan expired; refresh and approve a new plan")
    return plan


def subjects(plan):
    return (["mes://maintenance-events" + (f"/{plan['maintenance']['id']}" if plan["maintenance"] else "")]
            + [f"mes://work-orders/{p['order_id']}" for p in plan["placements"]]
            + [f"mes://lines/{i}" for i in {plan["affected_line_id"]}])


def validate_plan(plan):
    """Displayed effects and requests must describe the same finite operations."""
    from .commands import build_parser
    try:
        if plan["schema_version"] != 1 or not plan["placements"]:
            raise ValueError()
        for p in plan["placements"]:
            after = p["after"]
            if after["line_id"] != plan["affected_line_id"]:
                raise ValueError()
            if instant(after["planned_end_at"]) <= instant(after["planned_start_at"]):
                raise ValueError()
            if after["line_id"] == plan["affected_line_id"] and instant(after["planned_start_at"]) < instant(plan["maintenance_end"]):
                raise ValueError()
        if plan["maintenance_words"]:
            args = build_parser().parse_args(plan["maintenance_words"])
            if (args.command_name != "maintenance create" or int(args.line_id) != plan["affected_line_id"]
                    or instant(args.scheduled_at) != instant(plan["maintenance_start"])
                    or instant(args.scheduled_end_at) != instant(plan["maintenance_end"]) or args.dry_run):
                raise ValueError()
        elif not plan["maintenance"]:
            raise ValueError()
    except (KeyError, TypeError, AttributeError, SystemExit, ValueError):
        raise ValueError("Invalid recovery plan; prepare a new exact plan") from None


def instant(value):
    from ..machines.festo_cp_lab.replanning import instant as parse
    return parse(value)


def run(words, client, context):
    from .commands import build_parser
    from .executor import execute
    # Each request has its own attempt ID; all belong to the approved trace.
    return execute(build_parser().parse_args(words), client,
                   context=ExecutionContext(context.trace_id, context.execution_id + "-" + os.urandom(4).hex()))


def approval_detail(plan_id):
    plan = load(plan_id)
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(plan["timezone"])
    display = lambda value: instant(value).astimezone(zone).isoformat()
    if plan["maintenance"]:
        title = plan["maintenance"].get("title", "Maintenance")
    else:
        from .commands import build_parser
        title = build_parser().parse_args(plan["maintenance_words"]).title
    effects = [f"{'Reuse' if plan['maintenance'] else 'Create'} maintenance '{title}' on line {plan['affected_line_id']}: "
               f"{display(plan['maintenance_start'])} to {display(plan['maintenance_end'])} ({plan['timezone']})"]
    effects += [f"Order {p['order_no']} ({p['order_id']}): line {p['before']['line_id']} -> {p['after']['line_id']}, "
                f"{display(p['after']['planned_start_at'])} to {display(p['after']['planned_end_at'])}" for p in plan["placements"]]
    effects.append("After maintenance read-back, execute these exact moves automatically. No physical start or repair.")
    return {"effects": effects, "subjects": subjects(plan), "plan_id": plan_id,
            "expires_at": plan["expires_at"]}


def prepare(args, client, context):
    from ..machines.festo_cp_lab import replanning
    if args.maintenance_id:
        if any(getattr(args, k, None) is not None for k in ("title", "description", "start", "end")):
            raise MesError("An existing maintenance event supplies its persisted window; do not override it")
    elif not all(getattr(args, k, None) for k in ("title", "description", "start", "end")):
        raise MesError("New maintenance requires title, description, start and end")
    plan = replanning.proposal(args.asset, args.aas_endpoint, args.maintenance_id,
                             maintenance_start=args.start, maintenance_end=args.end, mes_client=client)
    if not plan["context"].get("ReplanningPolicy"):
        raise MesError("The selected ProductionContext does not configure a replanning policy")
    now = clock()
    if not args.maintenance_id and instant(plan["maintenance_start"]) <= now:
        raise MesError("Proposed maintenance start must be in the future")
    if not plan["placements"]:
        raise MesError("No order changes are needed; no integrated write plan was prepared")
    # Only unstarted demo orders are supported, even if a placement was skipped.
    if any(o.get("status") not in ("PENDING", "ACCEPTED") or float(o.get("produced_qty") or o.get("produced_quantity") or 0) > 0
           for o in plan["orders"]):
        raise MesError("Integrated recovery only moves accepted or pending, unstarted orders")
    maintenance_words = None
    maintenance_preview = None
    if not args.maintenance_id:
        maintenance_words = ["maintenance", "create", "--title", args.title, "--event-type", "corrective",
                             "--line", str(plan["affected_line_id"]), "--scheduled-at", plan["maintenance_start"],
                             "--scheduled-end-at", plan["maintenance_end"], "--description",
                             args.description + " A4S recovery trace: " + context.trace_id]
        ensure_no_existing_event(client, context.trace_id, plan["affected_line_id"])
        maintenance_preview = run(maintenance_words + ["--dry-run"], client, context)
    deadlines = [now + timedelta(minutes=10)] + [instant(p["after"]["planned_start_at"]) for p in plan["placements"]]
    if not args.maintenance_id:
        deadlines.append(instant(plan["maintenance_start"]))
    plan.update(schema_version=1, asset=args.asset, aas_endpoint=args.aas_endpoint,
                mes_endpoint=client.config.endpoint, timezone=client.config.server_timezone,
                trace_id=context.trace_id, expires_at=min(deadlines).isoformat(),
                maintenance_words=maintenance_words, maintenance_preview=maintenance_preview)
    plan["subjects"] = ["mes://maintenance-events" + (f"/{args.maintenance_id}" if args.maintenance_id else "")]
    plan["subjects"] += [f"mes://work-orders/{p['order_id']}" for p in plan["placements"]]
    plan["subjects"] += [f"mes://lines/{i}" for i in {plan["affected_line_id"]}]
    plan_id = digest(plan)
    directory().mkdir(parents=True, exist_ok=True)
    (directory() / (plan_id + ".json")).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return {"dry_run": True, "plan_id": plan_id, "expires_at": plan["expires_at"],
            "maintenance_id": args.maintenance_id, "maintenance_start": plan["maintenance_start"],
            "maintenance_end": plan["maintenance_end"], "duration_minutes": plan["duration_minutes"],
            "placements": [{k: p[k] for k in ("order_id", "order_no", "before", "after", "reason")} for p in plan["placements"]],
            "effects": approval_detail(plan_id)["effects"],
            "apply_command": f"mes recovery apply {plan_id} --trace-id {context.trace_id}",
            "note": "Approval of apply covers maintenance and all listed exact moves once. No separate move approvals."}


ORDER_FIELDS = ("id", "order_no", "line_id", "status", "product_type_id", "quantity", "produced_quantity",
                "planned_qty", "produced_qty", "priority", "due_date", "batches",
                "planned_start_at", "planned_end_at", "process_snapshot")


def ensure_no_existing_event(client, trace_id, line_id):
    for event in client.rows("/api/v1/maintenance-events", line_id=line_id):
        if event.get("line_id") == line_id and trace_id in (event.get("description") or ""):
            raise MesError(f"Maintenance for this fault already exists (ID {event['id']}); prepare with --maintenance-id")


def unchanged_order(before, after):
    for key in ORDER_FIELDS:
        if key in ("planned_start_at", "planned_end_at") and before.get(key) and after.get(key):
            if instant(before[key]) != instant(after[key]):
                return False
        elif before.get(key) != after.get(key):
            return False
    return True


def verify_maintenance(event, plan):
    if (event.get("line_id") != plan["affected_line_id"] or event.get("status") not in ("pending", "in_progress")
            or instant(event.get("scheduled_at")) != instant(plan["maintenance_start"])
            or instant(event.get("scheduled_end_at")) != instant(plan["maintenance_end"])):
        raise MesError("Persisted maintenance does not match the approved window; no further order moves")


def compact_write(step):
    actual = step.get("read_back", {}).get("data", {})
    return {k: step[k] for k in ("mutation", "execution", "affected_resources", "verified", "verification_error") if k in step} | {
        "read_back": {"data": {k: actual[k] for k in ("id", "line_id", "status", "scheduled_at", "scheduled_end_at",
                                                   "planned_start_at", "planned_end_at") if k in actual}}}


def preview_move(placement, client, context):
    # Build only the finite schedule move shown in the approval; never execute
    # a command string supplied by a file or model.
    after = placement["after"]
    words = ["schedule", "move", str(placement["order_id"]), "--line", str(after["line_id"]),
             "--start", after["planned_start_at"], "--end", after["planned_end_at"]]
    preview = run(words + ["--dry-run"], client, context)
    if preview["request_fingerprint"] != placement["preview"]["request_fingerprint"]:
        raise MesError("Prepared order request changed; refresh the recovery plan")
    from ..machines.festo_cp_lab.replanning import available_capacity
    begin, end = (instant(placement["after"][k]) for k in ("planned_start_at", "planned_end_at"))
    if available_capacity(preview, placement["after"]["line_id"], begin, end) < (end-begin).total_seconds()/3600:
        raise MesError("The approved target dates no longer have sufficient capacity")
    return words


def apply(args, client, context):
    from ..machines.festo_cp_lab import replanning
    from ..machines.festo_cp_lab.mes_binding import current_demo_orders, resolve_line
    plan = load(args.target)
    if (client.config.endpoint != plan["mes_endpoint"] or client.config.server_timezone != plan["timezone"]
            or context.trace_id != plan["trace_id"]):
        raise MesError("MES destination, timezone or event trace changed; prepare a new recovery plan")
    current_context = replanning.production_context(plan["asset"], plan["aas_endpoint"])
    if current_context != plan["context"]:
        raise MesError("AAS production references changed; prepare a new recovery plan")
    line = resolve_line(current_context, client)
    if {int(o["id"]) for o in current_demo_orders(client, line)} != {int(o["id"]) for o in plan["orders"]}:
        raise MesError("The demo orders changed or were reset; prepare a new recovery plan")
    for order in plan["orders"]:
        actual = run(["order", "show", str(order["id"])], client, context)["data"]
        if not unchanged_order(order, actual):
            raise MesError("An order changed since approval; prepare a new recovery plan")
    if plan["maintenance"]:
        event = run(["maintenance", "show", str(plan["maintenance"]["id"])], client, context)["data"]
        verify_maintenance(event, plan)
    else:
        ensure_no_existing_event(client, context.trace_id, plan["affected_line_id"])
        preview = run(plan["maintenance_words"] + ["--dry-run"], client, context)
        if preview["request_fingerprint"] != plan["maintenance_preview"]["request_fingerprint"]:
            raise MesError("Prepared maintenance request changed")
    for placement in plan["placements"]:
        preview_move(placement, client, context)
    if args.dry_run:
        return {"dry_run": True, "plan_id": args.target, **approval_detail(args.target)}
    # Recheck after network preflights and consume atomically before any write.
    load(args.target)
    try:
        with (directory() / (args.target + ".used")).open("x", encoding="utf-8") as marker:
            marker.write(context.execution_id)
    except FileExistsError:
        raise MesError("Recovery plan already attempted; inspect results before preparing another") from None
    result = {"plan_id": args.target, "verified": False, "maintenance_id": (plan["maintenance"] or {}).get("id"),
              "steps": [], "order_moves": [], "affected_resources": []}
    try:
        if plan["maintenance_words"]:
            step = run(plan["maintenance_words"], client, context)
            result["steps"].append(compact_write(step))
            result["affected_resources"].extend(step.get("affected_resources", []))
            if not step.get("verified"):
                raise MesError("Maintenance write was not verified; order changes were stopped")
            result["maintenance_id"] = step["read_back"]["data"]["id"]
        event = run(["maintenance", "show", str(result["maintenance_id"])], client, context)["data"]
        verify_maintenance(event, plan)
        result["maintenance"] = {k: event[k] for k in ("id", "line_id", "title", "status", "scheduled_at", "scheduled_end_at")}
        for placement in plan["placements"]:
            # Later steps may not reuse preflight evidence after an earlier write.
            verify_maintenance(run(["maintenance", "show", str(result["maintenance_id"])], client, context)["data"], plan)
            actual = run(["order", "show", str(placement["order_id"])], client, context)["data"]
            original = next(o for o in plan["orders"] if o["id"] == placement["order_id"])
            if not unchanged_order(original, actual) or instant(placement["after"]["planned_start_at"]) <= clock():
                raise MesError("Order state or approved future slot changed; remaining moves were stopped")
            words = preview_move(placement, client, context)
            step = run(words, client, context)
            result["steps"].append(compact_write(step))
            result["affected_resources"].extend(step.get("affected_resources", []))
            if not step.get("verified"):
                raise MesError("An order move was not verified; remaining moves were stopped")
            result["order_moves"].append({"order_id": placement["order_id"], "after": compact_write(step)["read_back"]["data"]})
        changes = client.rows("/api/v1/schedule/changes")
        ids = {p["order_id"] for p in plan["placements"]}
        result["schedule_changes"] = {"data": [c for c in changes if c.get("work_order_id") in ids][:10]}
        result["verified"] = True
    except (MesError, ValueError) as exc:
        result.update(error=str(exc), outcome="partial_or_unverified", failure_execution=getattr(exc, "execution", None),
                      warning="Inspect the recorded maintenance and orders. Never replay this plan or successful steps.")
    (directory() / (args.target + ".result.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def coordinate(args, client, context):
    previous = client.execution_context
    client.execution_context = context
    try:
        result = prepare(args, client, context) if args.command_name == "recovery prepare" else apply(args, client, context)
    except MesError as exc:
        if not getattr(exc, "execution", None):
            exc.execution = {**context.as_dict(), "action": args.command_name, "outcome": "preflight_failed"}
        raise
    finally:
        client.execution_context = previous
    return {**result, "execution": {**context.as_dict(), "action": args.command_name,
            "outcome": "previewed" if result.get("dry_run") else "verified" if result.get("verified") else "partial_or_unverified"}}
