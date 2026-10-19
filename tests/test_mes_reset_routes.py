"""UI reset remains previewed, one-shot and MES-only."""

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from a4s.server import production_routes as routes


def test_running_agent_blocks_reset_before_consuming_approval(monkeypatch):
    from a4s.server import chat
    monkeypatch.setattr(chat, 'agent_running', lambda: True)
    monkeypatch.setattr(routes, 'RESET_PREVIEWS', {'approved': {'expires_at': routes.time.time()+60}})
    monkeypatch.setattr(routes, '_reset_scope', lambda: pytest.fail('must not inspect or modify MES'))
    with pytest.raises(routes.HTTPException, match='Stop the running Agent'):
        routes.execute_reset({'id': 'approved', 'confirmed': True})
    assert 'approved' in routes.RESET_PREVIEWS


def test_reset_scope_refuses_unrelated_or_produced_orders(monkeypatch):
    monkeypatch.setattr(routes.Config, 'from_env', lambda: SimpleNamespace(endpoint='http://localhost:8092'))
    rows = {
        '/api/v1/lines': [{'id': 1, 'code': 'A4S-FESTO'}, {'id': 2, 'code': 'A4S-BACKUP'}],
        '/api/v1/product-types': [{'id': 3, 'code': 'A4S-DEMO-PART'}],
        '/api/v1/work-orders': [{'id': 4, 'order_no': 'OTHER-1', 'status': 'ACCEPTED', 'produced_qty': 0}],
        '/api/v1/maintenance-events': [],
    }

    class Mes:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def rows(self, path):
            return rows[path]

    monkeypatch.setattr(routes, 'MesClient', Mes)
    with pytest.raises(routes.HTTPException, match='non-A4S orders'):
        routes._reset_scope()
    rows['/api/v1/work-orders'][0].update(order_no='A4S-demo-A', produced_qty='1.00')
    with pytest.raises(routes.HTTPException, match='produced quantity'):
        routes._reset_scope()


@pytest.mark.parametrize('readback_change', [
    {}, {'planned_start_at': '2026-10-02T12:00:00Z'},
    {'planned_end_at': '2026-10-02T12:45:00Z'}, {'line_id': 2},
    {'planned_qty': 180}, {'produced_qty': 1}, {'status': 'IN_PROGRESS'},
])
def test_reset_preview_rechecks_mes_and_consumes_approval_once(monkeypatch, tmp_path, readback_change):
    sessions = []
    monkeypatch.setattr(routes, '_new_demo_session', lambda: sessions.append('new') or {'id': 'new', 'started_at': 1})
    monkeypatch.setattr(routes, 'service', SimpleNamespace(close=lambda: None))
    state = {'digest': 'before', 'endpoint': 'http://localhost:8092',
             'orders': [{'id': 1, 'order_no': 'A4S-demo-A', 'status': 'ACCEPTED'}],
             'maintenance_count': 1,
             'lines': [{'id': 1, 'code': 'A4S-FESTO'}, {'id': 2, 'code': 'A4S-BACKUP'}]}
    monkeypatch.setattr(routes, '_reset_scope', lambda: dict(state))
    monkeypatch.setattr(routes, 'RESET_PREVIEWS', {})
    monkeypatch.setattr(routes, 'ROOT', tmp_path)
    monkeypatch.setattr(routes, 'MANIFEST', tmp_path / 'current.json')
    calls = []
    class Clock(routes.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 6, 22, tzinfo=routes.timezone.utc)
    monkeypatch.setattr(routes, 'datetime', Clock)

    class Mes:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, path):
            manifest = json.loads(routes.MANIFEST.read_text())
            order = next(o for o in manifest['baseline'] if str(o['id']) == path.rsplit('/', 1)[-1])
            return {'data': {**order, **readback_change}}

    monkeypatch.setattr(routes, 'MesClient', Mes)
    monkeypatch.setattr(routes.Config, 'from_env', lambda: SimpleNamespace(server_timezone='Europe/Berlin'))

    def fake_run(argv, **kwargs):
        calls.append(argv)
        start = routes.datetime.fromisoformat(argv[argv.index('--start-at') + 1])
        schedule = routes.lots(start, 'Europe/Berlin')
        manifest = {'run_id': 'new-run', 'baseline': [
            {'id': 10+i, 'order_no': 'A4S-new-' + str(10+i), 'line_id': 1,
             'status': 'ACCEPTED', 'planned_qty': '90.00', 'produced_qty': '0.00',
             'planned_start_at': slot['planned_start_at'], 'planned_end_at': slot['planned_end_at']}
            for i, slot in enumerate(schedule)]}
        routes.MANIFEST.write_text(json.dumps(manifest), encoding='utf-8')
        return SimpleNamespace(stdout=json.dumps({'run_id': 'new-run', 'orders': manifest['baseline'],
            'archived_orders': 1, 'archived_maintenance': 1, 'backup': 'backup.dump'}))

    monkeypatch.setattr(routes.subprocess, 'run', fake_run)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        preview = client.post('/api/demo/festo/reset/preview')
        assert preview.status_code == 200
        assert preview.json()['maintenance_count'] == 1
        schedule = preview.json()['schedule']
        assert preview.json()['schedule_timezone'] == 'Europe/Berlin'
        assert schedule[0]['planned_start_at'] == '2026-10-06T23:00:00+00:00'
        assert [row['due_date'] for row in schedule] == ['2026-10-07']
        assert [slot['lot'] for slot in schedule] == ['A']
        assert len(schedule) == 1
        assert calls == []
        plan_id = preview.json()['id']
        assert client.post('/api/demo/festo/reset/execute', json={'id': plan_id}).status_code == 403
        state['digest'] = 'changed'
        assert client.post('/api/demo/festo/reset/execute', json={'id': plan_id, 'confirmed': True}).status_code == 409
        assert calls == []
        state['digest'] = 'before'
        approved = client.post('/api/demo/festo/reset/preview').json()
        plan_id = approved['id']
        result = client.post('/api/demo/festo/reset/execute', json={'id': plan_id, 'confirmed': True})
        if readback_change:
            assert result.status_code == 502
            assert sessions == []
        else:
            assert result.status_code == 200, result.text
            assert result.json()['aas_modified'] is False
            assert result.json()['demo_session']['id'] == 'new'
            assert sessions == ['new']
            assert [o['planned_start_at'] for o in result.json()['orders']] == [s['planned_start_at'] for s in approved['schedule']]
        assert len(calls) == 1 and calls[0][-1] == '--apply'
        assert calls[0][calls[0].index('--start-at') + 1] == approved['schedule'][0]['planned_start_at']
        assert client.post('/api/demo/festo/reset/execute', json={'id': plan_id, 'confirmed': True}).status_code == 409


def test_reset_rejects_schedule_that_is_no_longer_in_future(monkeypatch):
    monkeypatch.setattr(routes, '_reset_scope', lambda: {'digest': 'unchanged'})
    monkeypatch.setattr(routes, 'RESET_PREVIEWS', {'old': {
        'digest': 'unchanged', 'expires_at': routes.time.time() + 60,
        'start_at': '2026-09-28T12:00:00+00:00',
    }})
    monkeypatch.setattr(routes.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('reset must not run'))
    with pytest.raises(routes.HTTPException, match='Approved schedule is too close'):
        routes.execute_reset({'id': 'old', 'confirmed': True})
