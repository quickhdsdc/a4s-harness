"""Read current production references and propose maintenance-related MES placements."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import shlex
from contextlib import nullcontext
from zoneinfo import ZoneInfo

from ...aasctl.client import BasyxClient, Endpoint
from ...kernel.config import load_env
from ...mesctl.client import Config, MesClient, MesError
from ...mesctl.commands import build_parser
from ...mesctl.executor import execute
from .mes_binding import current_demo_orders, resolve_line


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Planning timestamps require an ISO timestamp with timezone offset') from None


def maintenance_interval(maintenance, start=None, end=None):
    """Use the persisted approved interval; never invent an end or default duration."""
    if maintenance:
        if start is not None or end is not None:
            raise ValueError('Use the persisted maintenance interval when an event ID is provided')
        start, end = maintenance.get('scheduled_at'), maintenance.get('scheduled_end_at')
    if not start or not end:
        raise ValueError('An explicit maintenance start and end are required; update legacy events before replanning')
    start, end = instant(start), instant(end)
    if end <= start:
        raise ValueError('Maintenance end must follow its start')
    return start, end


def available_capacity(preview, destination, begin, end):
    # Capacity day keys use MES wall-clock dates, including across UTC midnight.
    body = preview.get('body', {})
    begin = instant(body['planned_start_at']) if body.get('planned_start_at') else begin
    end = instant(body['planned_end_at']) if body.get('planned_end_at') else end
    capacity = preview.get('preflight', {}).get('capacity', {})
    resources = capacity.get('grid', capacity).get('resources', [])
    resource = next((r for r in resources if r['id'] == int(destination)), {})
    return sum(float(c.get('available_h', 0)) for day, c in resource.get('cells', {}).items()
               if begin.date().isoformat() <= day <= end.date().isoformat())


def production_context(asset, endpoint):
    with BasyxClient(Endpoint.from_env(endpoint)) as aas:
        shell = aas.get_shell(asset)
        models = [aas.get_submodel(k['value']) for ref in shell.get('submodels', [])
                  for k in ref.get('keys', []) if k['type'] == 'Submodel']
    contexts = [m for m in models if m.get('idShort') == 'ProductionContext']
    if len(contexts) != 1:
        raise ValueError('Exactly one ProductionContext is required')
    return {e['idShort']: e.get('value') for e in contexts[0]['submodelElements']}


def proposal(asset, endpoint, maintenance_id=None, *, maintenance_start=None, maintenance_end=None,
             mes_client=None):
    context = production_context(asset, endpoint)
    with nullcontext(mes_client) if mes_client is not None else MesClient(Config.from_env()) as mes:
        def read(words):
            return execute(build_parser().parse_args(words), mes)
        line = resolve_line(context, mes)
        selected = current_demo_orders(mes, line)
        orders = [read(['order', 'show', str(order['id'])])['data'] for order in selected]
        now = datetime.now(timezone.utc)
        earliest = now + timedelta(minutes=10)
        horizon = earliest.replace(second=0, microsecond=0)
        if horizon < earliest:
            horizon += timedelta(minutes=1)
        maintenance = read(['maintenance','show',str(maintenance_id)])['data'] if maintenance_id else None
        if maintenance and (maintenance.get('line_id') != int(line['id']) or
                            maintenance.get('status') not in ('pending','in_progress')):
            raise ValueError('Maintenance must be pending/in progress on the affected line')
        start, end = maintenance_interval(maintenance, maintenance_start, maintenance_end)
        if not maintenance and context.get('DemoMaintenanceStartDayOffset') is not None:
            days = int(context['DemoMaintenanceStartDayOffset'])
            if not 0 <= days <= 30:
                raise ValueError('Demo maintenance day offset must be between 0 and 30')
            zone = ZoneInfo(mes.config.server_timezone)
            original = min(instant(o['planned_start_at']) for o in orders).astimezone(zone)
            next_day = max(now.astimezone(zone).date(), original.date()) + timedelta(days=days)
            default_start = datetime.combine(next_day, original.timetz(), tzinfo=zone)
            proposed_duration = end - start
            start = max(start, default_start)
            end = start + proposed_duration
        if not maintenance and context.get('DemoMaintenanceWindowMinutes') is not None:
            minutes = int(context['DemoMaintenanceWindowMinutes'])
            if minutes <= 0 or minutes > 24 * 60:
                raise ValueError('Demo maintenance window must be between 1 and 1440 minutes')
            # Static demo reservation, displayed in the exact plan before approval.
            # Never change an already persisted maintenance event here.
            end = max(end, start + timedelta(minutes=minutes))
        buffer_minutes = int(context.get('DemoProductionReleaseBufferMinutes', 0))
        if not 0 <= buffer_minutes <= 24 * 60:
            raise ValueError('Demo production release buffer must be between 0 and 1440 minutes')
        release = end + timedelta(minutes=buffer_minutes)
        placements = []
        reason = f'Postpone the production order on Cell 1 until the persisted maintenance end plus {buffer_minutes} minutes of configured planning allowance.'
        for index, order in enumerate(orders):
            duration = instant(order['planned_end_at']) - instant(order['planned_start_at'])
            begin = max(instant(order['planned_start_at']), horizon, release)
            destination = line['id']
            words = ['schedule','move',str(order['id']),'--line',str(destination),
                     '--start',begin.isoformat(),'--end',(begin+duration).isoformat(),'--dry-run']
            if order['line_id'] == int(destination) and abs((instant(order['planned_start_at'])-begin).total_seconds()) < 1:
                continue
            preview = read(words)  # Existing product/routing/capacity preflight, no commit.
            available = available_capacity(preview, destination, begin, begin+duration)
            if available < duration.total_seconds() / 3600:
                raise MesError('Target line has insufficient available capacity in the proposed dates')
            placements.append({'order_id':order['id'],'order_no':order['order_no'],
                'before':{k:order.get(k) for k in ('line_id','planned_start_at','planned_end_at','status')},
                'after':{'line_id':int(destination),'planned_start_at':begin.isoformat(),'planned_end_at':(begin+duration).isoformat()},
                'reason':reason, 'preview_command':'mes '+shlex.join(words),
                'commit_command':'mes '+shlex.join(words[:-1]),'preview':preview})
        return {'current_time':now.isoformat(),'mes_line_code':line['code'],
                'context':context, 'affected_line_id':int(line['id']), 
                'orders':orders, 'maintenance':maintenance,'maintenance_start':start.isoformat(),'maintenance_end':end.isoformat(),
                'duration_minutes':(end-start).total_seconds()/60,'placements':placements,
                'note':'Read-only proposal. Use mes recovery prepare/apply for one approved maintenance and production plan. Recheck timestamps and conflicts at execution.'}


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset', required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--maintenance-id', type=int)
    parser.add_argument('--maintenance-start', help='Proposed ISO start with timezone, before event creation')
    parser.add_argument('--maintenance-end', help='Proposed ISO end with timezone, before event creation')
    args = parser.parse_args()
    print(json.dumps(proposal(args.asset,args.endpoint,args.maintenance_id,
        maintenance_start=args.maintenance_start, maintenance_end=args.maintenance_end), indent=2))


if __name__ == '__main__':
    main()
