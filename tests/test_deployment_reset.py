"""Deployment reset refuses target drift and cannot replay partial writes."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from a4s.machines.festo_cp_lab import demo_reset as scope
from a4s.machines.festo_cp_lab import reset_service as service


def test_remote_reset_requires_explicit_matching_target_and_secret(monkeypatch):
    for key in ('A4S_DEMO_RESET_URL','A4S_DEMO_RESET_MES_ENDPOINT','A4S_DEMO_RESET_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    assert scope.reset_target('http://localhost:8092') is None
    with pytest.raises(scope.ResetRefused):
        scope.reset_target('http://nuc:8092')
    monkeypatch.setenv('A4S_DEMO_RESET_URL','http://demo-reset:8093')
    monkeypatch.setenv('A4S_DEMO_RESET_MES_ENDPOINT','http://nuc:8092')
    with pytest.raises(scope.ResetRefused):
        scope.reset_target('http://nuc:8092')
    monkeypatch.setenv('A4S_DEMO_RESET_TOKEN','test-only-secret'*4)
    assert scope.reset_target('http://nuc:8092') == 'http://demo-reset:8093'
    with pytest.raises(scope.ResetRefused):
        scope.reset_target('http://other:8092')


@pytest.fixture
def request_body(monkeypatch):
    monkeypatch.setenv('DEMO_MES_PUBLIC_ENDPOINT','http://nuc:8092')
    monkeypatch.setenv('A4S_MES_TIMEZONE','Europe/Berlin')
    monkeypatch.setenv('DEMO_RESET_ARCHIVE_KEY','test-only-archive-secret'*2)
    monkeypatch.setattr(service.Config,'from_env',lambda: SimpleNamespace(endpoint='http://openmes:8000'))
    start=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    return {'id':'a'*32,'digest':'approved','endpoint':'http://nuc:8092',
            'start_at':start,'timezone':'Europe/Berlin','schedule':scope.approved_schedule(start,'Europe/Berlin')}


class FakeMes:
    def __init__(self,*_):
        self.http=SimpleNamespace(headers={})
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def request(self,*args,**kwargs):
        raise RuntimeError('archive outcome unknown')


@pytest.mark.parametrize('failure', ['backup','drift','archive'])
def test_reset_failure_phase_and_replay_guards(monkeypatch,tmp_path,request_body,failure):
    monkeypatch.setattr(service,'MesClient',FakeMes)
    inspected=[]
    def inspect(*_):
        inspected.append(1)
        return {'digest':'changed' if failure=='drift' and len(inspected)>1 else 'approved',
                'orders':[], 'maintenance':[], 'lines':[{'id':1},{'id':2}], 'product_id':3}
    monkeypatch.setattr(service,'inspect_scope',inspect)
    def backup(directory):
        if failure=='backup': raise RuntimeError('backup failed')
        destination=directory/'openmes-before.dump'
        destination.write_bytes(b'backup')
        return destination
    monkeypatch.setattr(service,'backup_database',backup)
    with pytest.raises((RuntimeError,scope.ResetRefused)):
        service.perform_reset(request_body,tmp_path)
    state=json.loads((tmp_path/request_body['id']/'state.json').read_text())
    assert state['phase']==('uncertain' if failure=='archive' else 'safe_failure')
    with pytest.raises(scope.ResetRefused):
        service.perform_reset(request_body,tmp_path)
    if failure=='archive':
        request_body['id']='b'*32
        with pytest.raises(scope.ResetRefused,match='previous reset'):
            service.perform_reset(request_body,tmp_path)


def test_approved_schedule_rejects_naive_or_elapsed_times():
    for value in ('2026-01-01T00:00:00','2026-01-01T00:00:00Z'):
        with pytest.raises(scope.ResetRefused):
            scope.approved_schedule(value,'Europe/Berlin',datetime(2026,2,1,tzinfo=timezone.utc))


@pytest.mark.parametrize('readback_ok',[True,False])
def test_backend_persists_remote_manifest_only_after_readback(monkeypatch,tmp_path,readback_ok):
    from a4s.server import production_routes as routes, demo_reset_client, chat
    monkeypatch.setenv('A4S_DEMO_RESET_URL','http://demo-reset:8093')
    monkeypatch.setattr(chat,'agent_running',lambda:False)
    monkeypatch.setattr(routes,'RESET_PREVIEWS',{})
    monkeypatch.setattr(routes,'MANIFEST',tmp_path/'current.json')
    monkeypatch.setattr(routes.Config,'from_env',lambda:SimpleNamespace(server_timezone='Europe/Berlin'))
    monkeypatch.setattr(routes,'_reset_scope',lambda:{'digest':'unchanged','endpoint':'http://nuc:8092',
        'orders':[],'maintenance_count':0,'lines':[{'id':1},{'id':2}]})
    monkeypatch.setattr(routes,'service',SimpleNamespace(close=lambda:None))
    sessions=[]
    monkeypatch.setattr(routes,'_new_demo_session',lambda:sessions.append(1) or {'id':'new'})
    manifest={}
    def remote(identifier,preview,state,zone):
        manifest.update(run_id='remote-test',baseline=[{'id':10+i,'order_no':f'A4S-test-{i}',
            'status':'ACCEPTED','line_id':1,'planned_qty':90,'produced_qty':0,
            'planned_start_at':slot['planned_start_at'],'planned_end_at':slot['planned_end_at']}
            for i,slot in enumerate(preview['schedule'])])
        return {'run_id':'remote-test','orders':manifest['baseline'],'archived_orders':0,
            'archived_maintenance':0,'backup':'demo-reset:/backups/test/openmes-before.dump'},manifest
    monkeypatch.setattr(demo_reset_client,'execute_service',remote)
    class Mes(FakeMes):
        def get(self,path):
            order=next(o for o in manifest['baseline'] if str(o['id'])==path.rsplit('/',1)[-1])
            return {'data':{**order,'produced_qty':0 if readback_ok else 1}}
    monkeypatch.setattr(routes,'MesClient',Mes)
    monkeypatch.setattr(routes.subprocess,'run',lambda *_args,**_kwargs:pytest.fail('host Docker must not run'))
    preview=routes.preview_reset()
    if readback_ok:
        assert routes.execute_reset({'id':preview['id'],'confirmed':True})['demo_session']['id']=='new'
        assert json.loads(routes.MANIFEST.read_text())['run_id']=='remote-test'
        assert sessions==[1]
    else:
        with pytest.raises(routes.HTTPException) as error:
            routes.execute_reset({'id':preview['id'],'confirmed':True})
        assert error.value.status_code==502
        assert not routes.MANIFEST.exists() and not sessions
