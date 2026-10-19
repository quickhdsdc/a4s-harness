"""A demo reset discards transient evidence, not audited actions or Start guards."""
import threading
import time

from fastapi.testclient import TestClient
import pytest

from a4s.ledger import Ledger
from a4s.machines.festo_cp_lab import demo_monitor, opc_simulator
from a4s.machines.festo_cp_lab.live_monitor import Monitor
from a4s.server import agent_activity, demo_session, festo_demo_routes, festo_start_routes
from a4s.server import live_monitor_routes, production_routes
from a4s.server.app import build_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monitor = Monitor(tmp_path / 'monitor.db', lambda _: {'values': []})
    monkeypatch.setattr(live_monitor_routes, 'service', monitor)
    simulator = opc_simulator.SimulatorController()
    simulator._mode = 'fault'
    monkeypatch.setattr(opc_simulator, 'controller', simulator)
    monkeypatch.setattr(demo_monitor, 'STATE', {
        'run_id': 'previous', 'active': True, 'started_at': time.time(), 'transitions': []})
    monkeypatch.setattr(festo_demo_routes, 'PLANS', {'old': {}})
    monkeypatch.setattr(production_routes, 'RESET_PREVIEWS', {'old': {}})
    monkeypatch.setattr(festo_start_routes, 'DIRECTORY', tmp_path / 'starts')
    monkeypatch.setattr(agent_activity, '_home', lambda: tmp_path)
    monkeypatch.setattr(demo_session, '_session', {'id': 'previous', 'started_at': 0})
    yield monitor, simulator, tmp_path
    monitor.close()


def test_startup_and_reset_clear_transient_history_and_preserve_ledger(isolated, monkeypatch):
    monitor, simulator, tmp_path = isolated
    target = {'source': 'simulator'}
    monitor.ingest(target, {'values': [], 'observed_at': time.time()})
    with Ledger(tmp_path / 'ledger.db', 'agent-old') as ledger:
        ledger.append('tool.result', {'tool': 'shell', 'call_id': 'old', 'output': 'kept'})
        head = ledger.head()
    app = build_app()
    def offline(*_args):
        raise RuntimeError('offline MES')
    monkeypatch.setattr(production_routes, 'workflow', offline)
    monkeypatch.setattr(production_routes, 'MANIFEST', tmp_path / 'missing.json')
    with TestClient(app) as client:
        first = client.get('/api/demo/festo/session').json()
        assert first['id'] != 'previous'
        assert monitor.status(target)['events'] == []
        assert monitor.status(target)['state'] == {}
        assert simulator.status()['mode'] == 'normal'
        assert not simulator.status()['running']
        assert demo_monitor.STATE == {'active': False, 'run_id': None, 'started_at': None}
        assert not festo_demo_routes.PLANS and not production_routes.RESET_PREVIEWS
        second = demo_session.reset()
        assert second['id'] != first['id']
        assert client.get('/api/agent/ledger/storage').json()['records'] == 1
        assert len(production_routes.activity(0, False)['activity']) == 1
    with Ledger(tmp_path / 'ledger.db', 'check') as ledger:
        assert ledger.head() == head
        assert ledger.verify()[0]


def test_late_inflight_read_cannot_recreate_deleted_history(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def reader(_target):
        entered.set()
        assert release.wait(3)
        return {'values': []}
    monitor = Monitor(tmp_path / 'monitor.db', reader, interval=.01)
    target = {'source': 'live'}
    try:
        monitor.start(target)
        assert entered.wait(1)
        monitor.reset()
        assert not monitor.status(target)['running']
        with pytest.raises(ValueError, match='still stopping'):
            monitor.start(target)
    finally:
        release.set()
        monitor.close()
        for _stop, thread in monitor.workers.values():
            thread.join(2)
    assert monitor.status(target)['events'] == []
    assert monitor.status(target)['state'] == {}


def test_old_completed_start_hidden_but_uncertain_guard_survives(isolated, monkeypatch):
    _monitor, _simulator, _path = isolated
    start = festo_start_routes
    old = {'id': 'old', 'status': 'finished', 'created_at': time.time() - 10, 'owner': start.OWNER}
    start.save(old)
    demo_session.reset()
    assert start.latest()['run'] is None
    old['status'] = 'needs_review'
    start.save(old)
    with start.database() as db:
        db.execute('UPDATE guard SET run=? WHERE id=1', (old['id'],))
    demo_session.reset()
    assert start.latest()['run']['id'] == old['id']
    with start.database() as db:
        assert db.execute('SELECT run FROM guard').fetchone()[0] == old['id']
    assert start.fetch(old['id'])['status'] == 'needs_review'


def test_reset_invalidates_physical_start_preview_without_writing(isolated, monkeypatch):
    monkeypatch.setattr(festo_start_routes, 'bindings', lambda: 'binding')
    app = build_app()
    origin = {'origin': 'http://localhost:5173'}
    with TestClient(app) as client:
        plan = client.post('/api/festo/start/preview', headers=origin).json()
        demo_session.reset()
        response = client.post('/api/festo/start/execute', headers=origin, json={
            'id': plan['id'], 'approved': True, 'onsite_safe': True})
        assert response.status_code == 409
        assert festo_start_routes.fetch(plan['id'])['status'] == 'preview'


def test_storage_report_is_readonly_and_missing_ledger_is_not_created(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_activity, '_home', lambda: tmp_path)
    assert not agent_activity.ledger_storage()['available']
    assert not (tmp_path / 'ledger.db').exists()
    with Ledger(tmp_path / 'ledger.db', 'one') as ledger:
        ledger.append('tool.result', {'tool': 'shell', 'output': 'secret stays private'})
        head = ledger.head()
    report = agent_activity.ledger_storage()
    assert report['records'] == report['sessions'] == 1
    assert report['bytes'] >= (tmp_path / 'ledger.db').stat().st_size
    assert not report['archive_recommended']
    assert 'secret' not in str(report)
    with Ledger(tmp_path / 'ledger.db', 'check') as ledger:
        assert ledger.head() == head


def test_agent_reset_clears_incidents_and_rotates_session_without_mes_or_plc(isolated, monkeypatch):
    monitor, simulator, tmp_path = isolated
    from a4s.server import chat
    monkeypatch.setattr(chat, 'agent_running', lambda: False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Agent reset must not access MES or send PLC commands')
    monkeypatch.setattr(production_routes, '_reset_scope', forbidden)
    with Ledger(tmp_path / 'ledger.db', 'old') as ledger:
        ledger.append('tool.result', {'tool': 'shell', 'output': 'retain audit'})
        original_head = ledger.head()
    with TestClient(build_app()) as client:
        simulator._mode = 'fault'
        monitor.ingest({'asset_id': 'old'}, {'values': [], 'observed_at': time.time()})
        before = client.get('/api/demo/festo/session').json()
        response = client.post('/api/demo/festo/session/reset', headers={'origin': 'http://localhost:5173'})
        assert response.status_code == 200, response.text
        after = response.json()['demo_session']
        assert after['id'] != before['id'] and after['started_at'] >= before['started_at']
        assert response.json()['monitoring'] == 'stopped'
        assert not monitor.status({'asset_id': 'old'})['events']
        assert not monitor.status({'asset_id': 'old'})['state']
        assert simulator.status()['mode'] == 'fault'
        monkeypatch.setattr(chat, 'agent_running', lambda: True)
        response = client.post('/api/demo/festo/session/reset', headers={'origin': 'http://localhost:5173'})
        assert response.status_code == 409
        assert client.get('/api/demo/festo/session').json() == after
    with Ledger(tmp_path / 'ledger.db', 'inspect') as ledger:
        assert ledger.head() == original_head
