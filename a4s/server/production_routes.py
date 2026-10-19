"""Read-only production/incident projection from OpenMES and recorded OPC evidence."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import httpx
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, Query

from .festo_demo_routes import snapshot
from .live_monitor_routes import service, target
from ..aasctl.client import Endpoint
from ..mesctl.client import Config, MesClient
from ..mesctl.client import MesError
from ..machines.festo_cp_lab.production_schedule import lots, next_start

router = APIRouter(prefix='/api/demo/festo')
MANIFEST = Path(__file__).resolve().parents[2] / 'work/temp/production-runs/current.json'
ROOT = Path(__file__).resolve().parents[2]
RESET_LOCK = threading.Lock()
RESET_PREVIEWS = {}
RESET_PREVIEW_LOCK = threading.Lock()
RESET_TIMEOUT_SECONDS = 600


def _reset_scope():
    """Inspect the explicitly configured demo MES; never use AAS order IDs."""
    from ..machines.festo_cp_lab.demo_reset import inspect_scope, reset_target, ResetRefused
    config = Config.from_env()
    try:
        reset_target(config.endpoint)
        with MesClient(config) as mes:
            return inspect_scope(mes, config.endpoint)
    except ResetRefused as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/reset/preview')
def preview_reset():
    if RESET_LOCK.locked():
        raise HTTPException(409, 'Another MES reset is in progress')
    try:
        scope = _reset_scope()
    except (MesError, ValueError) as exc:
        raise HTTPException(503, f'Cannot preview local MES reset ({type(exc).__name__})') from exc
    plan_id = uuid.uuid4().hex
    expires_at = time.time() + 300
    zone = Config.from_env().server_timezone
    start_at = next_start(datetime.now(timezone.utc), zone)
    schedule = lots(start_at, zone)
    with RESET_PREVIEW_LOCK:
        for key in list(RESET_PREVIEWS):
            if RESET_PREVIEWS[key]['expires_at'] < time.time():
                del RESET_PREVIEWS[key]
        if len(RESET_PREVIEWS) >= 100:
            raise HTTPException(429, 'Too many pending reset previews; wait for expiry')
        RESET_PREVIEWS[plan_id] = {'digest': scope['digest'], 'expires_at': expires_at,
                                   'start_at': start_at.isoformat(), 'schedule': schedule}
    return {'id': plan_id, 'expires_at': expires_at, 'endpoint': scope['endpoint'],
            'orders': scope['orders'], 'maintenance_count': scope['maintenance_count'],
            'lines': scope['lines'], 'new_order_count': 1, 'schedule': schedule,
            'schedule_timezone': zone,
            'effects': ['Back up the demo OpenMES PostgreSQL database before changes.',
                        'Archive existing A4S orders and maintenance on Cell 1 (including retirement of the old virtual backup).',
                        'Clear their planner changes, refresh demo shifts, and create one accepted 90-piece order.',
                        'Start a clean demo: stop monitoring and clear its events, charts and chat pane; preserve the Agent ledger.',
                        'Leave AAS instances, blueprints, OPC signals, accounts and unrelated MES configuration unchanged.']}


@router.post('/reset/execute')
def execute_reset(body: dict = Body(...)):
    if body.get('confirmed') is not True:
        raise HTTPException(403, 'Explicit reset confirmation is required')
    from .chat import agent_running
    if agent_running():
        raise HTTPException(409, 'Stop the running Agent task before resetting the demo MES')
    if not RESET_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Another MES reset is in progress')
    try:
        if agent_running():
            raise HTTPException(409, 'Stop the running Agent task before resetting the demo MES')
        with RESET_PREVIEW_LOCK:
            preview = RESET_PREVIEWS.pop(str(body.get('id', '')), None)
        if not preview or preview['expires_at'] < time.time():
            raise HTTPException(409, 'Reset preview expired or was already used; preview again')
        try:
            scope = _reset_scope()
        except (MesError, ValueError) as exc:
            raise HTTPException(503, f'Cannot recheck local MES reset ({type(exc).__name__})') from exc
        if scope['digest'] != preview['digest']:
            raise HTTPException(409, 'MES state changed since preview; refresh and preview again')
        start_at = datetime.fromisoformat(preview['start_at'])
        if start_at < datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(409, 'Approved schedule is too close to the current time; preview again')
        # Stop handoffs while MES is being reset. Clear history only after
        # successful read-back; failed or uncertain resets keep the evidence.
        service.close()
        try:
            remote = bool(os.getenv('A4S_DEMO_RESET_URL'))
            if remote:
                from .demo_reset_client import execute_service
                outcome, manifest = execute_service(str(body['id']), preview, scope,
                                                    Config.from_env().server_timezone)
            else:
                completed = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/reset-production-plan.py'),
                     '--start-at', preview['start_at'], '--apply'],
                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                    timeout=RESET_TIMEOUT_SECONDS, check=True,
                )
                outcome = json.loads(completed.stdout)
                manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
            if outcome.get('run_id') != manifest.get('run_id') or len(manifest.get('baseline', [])) != 1:
                raise ValueError('Reset manifest read-back does not match the completed run')
            with MesClient(Config.from_env()) as mes:
                for expected, slot in zip(manifest['baseline'], preview['schedule']):
                    actual = mes.get(f"/api/v1/work-orders/{expected['id']}")['data']
                    if (actual.get('order_no') != expected['order_no'] or
                            actual.get('status') != 'ACCEPTED' or
                            actual.get('line_id') != scope['lines'][0]['id'] or
                            float(actual.get('planned_qty') or 0) != 90 or
                            float(actual.get('produced_qty') or 0) != 0 or
                            any(epoch(actual.get(key)) != epoch(slot[key]) or
                                epoch(expected.get(key)) != epoch(slot[key])
                                for key in ('planned_start_at', 'planned_end_at'))):
                        raise ValueError('New MES order read-back differs from the reset manifest')
            if remote:
                MANIFEST.parent.mkdir(parents=True, exist_ok=True)
                staging = MANIFEST.with_suffix('.json.tmp')
                staging.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                staging.replace(MANIFEST)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, httpx.HTTPError,
                ValueError, MesError, KeyError) as exc:
            raise HTTPException(502, 'MES reset failed or its outcome is uncertain. Inspect OpenMES and the backup before retrying; do not assume a retry is safe.') from exc
        return {'run_id': outcome['run_id'], 'orders': outcome['orders'],
                'archived_orders': outcome['archived_orders'],
                'archived_maintenance': outcome['archived_maintenance'],
                'backup': outcome['backup'], 'aas_modified': False,
                'demo_session': _new_demo_session()}
    finally:
        RESET_LOCK.release()


def _new_demo_session():
    from .demo_session import reset
    return reset()


def epoch(value):
    if isinstance(value, (int, float)):
        return value
    if not value:
        return 0
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


def in_window(rows, since, field='created_at'):
    return [row for row in rows if epoch(row.get(field)) >= since]


def delivery_summary(order, timezone_name):
    zone = ZoneInfo(timezone_name or 'UTC')
    due = order.get('due_date')
    end = order.get('planned_end_at')
    def local_day(value):
        if 'T' not in value and ' ' not in value:
            return value[:10]
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(zone).date().isoformat()
    due_day = local_day(due) if due else None
    return {'due_day': due_day,
            'planned_after_due': bool(due_day and end and local_day(end) > due_day)}


@router.get('/activity')
def activity(hours: int = Query(1, ge=0, le=168), current_run: bool = True):
    from .agent_activity import ledger_activity

    since = time.time() - hours * 3600 if hours else 0
    warnings = []
    mes_url = None
    try:
        projection = workflow(hours, current_run)
        since = max(since, epoch(projection['started_at']) if current_run else 0)
        mes_url = projection.get('mes_url')
    except Exception:
        projection = {'activity': [], 'started_at': None}
        warnings.append('MES / OPC activity unavailable; showing available agent ledger records.')
        # The last local reset timestamp is only a fallback when MES cannot be
        # reached; never use it to select orders or attach an asset.
        if current_run and MANIFEST.exists():
            try:
                projection['started_at'] = json.loads(MANIFEST.read_text(encoding='utf-8')).get('started_at')
                since = max(since, epoch(projection['started_at']))
            except (OSError, ValueError, TypeError):
                pass
    try:
        result = ledger_activity(since)
        if not result['ledger_available']:
            warnings.append('Agent ledger has not been created yet.')
    except Exception as exc:
        result = {'activity': [], 'ledger_available': False, 'ledger_truncated': False}
        warnings.append(f'Agent ledger unavailable ({type(exc).__name__}).')
    result['activity'].extend(projection['activity'])
    result['activity'].sort(key=lambda row: row['at'], reverse=True)
    return {**result, 'started_at': projection.get('started_at'), 'warnings': warnings,
            'scope': 'Workspace agent ledger + current Festo MES / OPC events',
            'since': datetime.fromtimestamp(since, timezone.utc).isoformat(),
            'mes_url': mes_url}


@router.get('/workflow')
def workflow(hours: int = Query(1, ge=0, le=168), current_run: bool = True):
    try:
        state = snapshot()
        manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
        orders = [state['order']]
        order_ids = {o['id'] for o in orders}
        same_run = (manifest.get('mes_endpoint') == state['mes_url'] and
                    {o.get('id') for o in manifest.get('baseline', [])} == order_ids)
        begin = min(epoch(o.get('created_at')) for o in orders)
        if not begin:
            begin = epoch(manifest.get('started_at')) if same_run else 0
        run_id = orders[0]['order_no'].rpartition('-')[0]
        from .demo_session import status as demo_status
        since = max(time.time()-hours*3600 if hours else 0, begin if current_run else 0,
                    demo_status()['started_at'])
        with MesClient(Config.from_env()) as mes:
            maintenance = mes.rows('/api/v1/maintenance-events', line_id=state['line']['id'])
            raw_changes = mes.get('/api/v1/schedule/changes')
        changes = raw_changes.get('changes', raw_changes.get('data', []))
        changes = [c for c in changes if c.get('work_order_id') in order_ids]
        # Initial placements are baseline setup; subsequent edits are replanning evidence.
        changes = in_window(changes, max(since, epoch(manifest.get('ready_at')) if same_run else begin))
        maintenance = in_window(maintenance, since)
        events = []
        endpoint = Endpoint.from_env().base_url
        for source in ('live','simulator'):
            report = service.status(target(state['asset']['id'], endpoint, source))
            events.extend(e for e in report['events'] if e['at'] >= since)
        events.sort(key=lambda e:e['at'])
        faults = [e for e in events if e['kind'] in ('FAULT_RAISED','BASELINE_FAULT','FAULT_OBSERVED_AFTER_GAP',
                  'PROCESS_INTERVENTION_RAISED','BASELINE_PROCESS_INTERVENTION','PROCESS_INTERVENTION_AFTER_GAP',
                  'LEAK_SUSPECTED')]
        baseline = {o['id']:o for o in manifest.get('baseline', [])} if same_run else {}
        activity = [{'at':e['at'],'type':'OPC','title':{
            'FAULT_RAISED':'New station fault detected','BASELINE_FAULT':'Fault present when monitoring began',
            'RECOVERY_OBSERVED':'Fault signals cleared','COMMUNICATION_LOST':'OPC connection unavailable',
            'COMMUNICATION_RESTORED':'OPC connection restored',
        }.get(e['kind'],e['kind']), 'detail': 'Agent analysis requested' if e.get('claimed') else 'Evidence recorded',
            'evidence':e} for e in events]
        for m in maintenance:
            activity.append({'at':epoch(m['created_at']),'type':'Maintenance','title':f"Maintenance #{m['id']} created",
                             'detail':m['title'], 'evidence':m})
        for c in changes:
            activity.append({'at':epoch(c['created_at']),'type':'Planning','title':f"{c.get('order_no')} rescheduled",
                             'detail':c.get('user') or 'MES planner', 'evidence':c})
        return {'run_id':run_id,'started_at':datetime.fromtimestamp(begin, timezone.utc).isoformat() if begin else None,
                'since':datetime.fromtimestamp(since,timezone.utc).isoformat(),
                'orders':[{'current':o,'initial':baseline.get(o['id']),
                           **delivery_summary(o, Config.from_env().server_timezone)} for o in orders],
                'lines':[state['line']], 'maintenance':maintenance,
                'changes':changes, 'faults':faults,
                'activity':sorted(activity,key=lambda e:e['at'],reverse=True),
                'mes_url':state['mes_url'],'read_at':time.time()}
    except Exception as exc:
        raise HTTPException(503, f'Production workflow unavailable ({type(exc).__name__})') from exc
