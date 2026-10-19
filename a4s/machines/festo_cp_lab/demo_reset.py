"""Fixed demo reset scope shared by the UI and the deployment reset service."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from urllib.parse import urlsplit

from .production_schedule import lots


class ResetRefused(ValueError):
    pass


def reset_target(endpoint):
    service = os.getenv('A4S_DEMO_RESET_URL', '').strip().rstrip('/')
    if service:
        parsed = urlsplit(service)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ResetRefused('Invalid configured demo reset service')
        if endpoint != os.getenv('A4S_DEMO_RESET_MES_ENDPOINT', '').rstrip('/'):
            raise ResetRefused('Demo reset is not enabled for the configured MES')
        if len(os.getenv('A4S_DEMO_RESET_TOKEN', '')) < 32:
            raise ResetRefused('Demo reset service credential is missing')
        return service
    if endpoint != 'http://localhost:8092':
        raise ResetRefused('Production reset requires the local OpenMES or an explicitly configured demo reset service')
    return None


def inspect_scope(mes, endpoint):
    lines = mes.rows('/api/v1/lines')
    resolved = {}
    for code in ('A4S-FESTO', 'A4S-BACKUP'):
        matches = [row for row in lines if row.get('code') == code]
        if code == 'A4S-BACKUP' and not matches:
            continue
        if len(matches) != 1:
            raise ResetRefused(f'Expected one demo MES line with code {code}')
        resolved[code] = matches[0]
    products = [row for row in mes.rows('/api/v1/product-types') if row.get('code') == 'A4S-DEMO-PART']
    if len(products) != 1:
        raise ResetRefused('Expected one A4S demo product type')
    orders = sorted(mes.rows('/api/v1/work-orders'), key=lambda row: int(row['id']))
    unrelated = [row for row in orders if not str(row.get('order_no', '')).startswith('A4S-')]
    if unrelated:
        raise ResetRefused(f'{len(unrelated)} non-A4S orders exist; demo reset is blocked')
    if any(row.get('status') == 'IN_PROGRESS' or float(row.get('produced_qty') or 0) > 0 for row in orders):
        raise ResetRefused('An A4S order is active or has produced quantity; reset is blocked')
    ids = {int(row['id']) for row in resolved.values()}
    if any(int(row.get('line_id') or 0) not in ids for row in orders):
        raise ResetRefused('An A4S order belongs to another line; demo reset is blocked')
    maintenance = sorted((row for row in mes.rows('/api/v1/maintenance-events')
                          if int(row.get('line_id') or 0) in ids), key=lambda row: int(row['id']))
    order_fields = ('id', 'order_no', 'status', 'produced_qty', 'updated_at')
    event_fields = ('id', 'status', 'updated_at')
    evidence = {'endpoint': endpoint,
        'lines': [(code, resolved[code]['id']) for code in resolved],
        'product_id': products[0]['id'],
        'orders': [tuple(row.get(k) for k in order_fields) for row in orders],
        'maintenance': [tuple(row.get(k) for k in event_fields) for row in maintenance]}
    return {'digest': hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
        'endpoint': endpoint, 'lines': [resolved[code] for code in resolved],
        'orders': [{k:row.get(k) for k in order_fields} for row in orders],
        'maintenance': [{k:row.get(k) for k in event_fields} for row in maintenance],
        'maintenance_count': len(maintenance), 'product_id': products[0]['id']}


def approved_schedule(start_at, zone, now=None):
    start = datetime.fromisoformat(start_at.replace('Z', '+00:00'))
    if start.tzinfo is None or start.utcoffset() is None:
        raise ResetRefused('Approved reset slot needs a timezone')
    if start < (now or datetime.now(timezone.utc)) + timedelta(minutes=5):
        raise ResetRefused('Approved reset slot is too close to the current time')
    return lots(start.astimezone(timezone.utc), zone)
