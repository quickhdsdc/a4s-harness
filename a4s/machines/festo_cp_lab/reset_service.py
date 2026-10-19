"""Private, fixed-purpose demo reset coordinator with PostgreSQL backups.

Runs without a Docker socket or AAS/OPC/model credentials. OpenMES performs the
archive through its own model hooks; normal MES APIs create/accept/schedule lots.
"""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import threading

from .demo_reset import ResetRefused, approved_schedule, inspect_scope
from ...mesctl.client import Config, MesClient
from ...mesctl.commands import build_parser
from ...mesctl.executor import execute

LOCK = threading.Lock()


def write_json(path, body):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(body, indent=2), encoding='utf-8')
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def backup_database(directory):
    destination = directory/'openmes-before.dump'
    subprocess.run(['pg_dump', '-h', os.environ['PGHOST'], '-U', os.environ['PGUSER'],
                    '-d', os.environ['PGDATABASE'], '-Fc', '-f', str(destination)],
                   check=True, capture_output=True, timeout=180)
    if destination.stat().st_size < 1000:
        raise ResetRefused('Database backup is unexpectedly small')
    subprocess.run(['pg_restore', '--list', str(destination)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    os.chmod(destination, 0o600)
    return destination


def perform_reset(body, root=None):
    public = os.environ['DEMO_MES_PUBLIC_ENDPOINT'].rstrip('/')
    zone = os.environ.get('A4S_MES_TIMEZONE', 'Europe/Berlin')
    if set(body) != {'id','digest','endpoint','start_at','schedule','timezone'}:
        raise ResetRefused('Unexpected reset request fields')
    if not re.fullmatch('[0-9a-f]{32}', str(body['id'])):
        raise ResetRefused('Invalid reset request identity')
    if body['endpoint'] != public or body['timezone'] != zone:
        raise ResetRefused('Reset target does not match this demonstration deployment')
    schedule = approved_schedule(body['start_at'], zone)
    if schedule != body['schedule']:
        raise ResetRefused('Reset schedule differs from the approved slots')
    root = root or Path(os.getenv('DEMO_RESET_BACKUPS', '/backups'))
    root.mkdir(parents=True, exist_ok=True)
    for entry in root.glob('*/state.json'):
        state = json.loads(entry.read_text())
        if state['phase'] in ('archiving','creating','uncertain'):
            raise ResetRefused('A previous reset is incomplete; review its backup and MES before retrying')
    directory = root/body['id']
    if directory.exists():
        raise ResetRefused('This reset request has already been consumed')
    config = Config.from_env()
    if config.endpoint != 'http://openmes:8000':
        raise ResetRefused('Reset coordinator may only contact its internal OpenMES service')
    with MesClient(config) as mes:
        scope = inspect_scope(mes, public)
        if scope['digest'] != body['digest']:
            raise ResetRefused('MES state changed since preview')
        directory.mkdir(mode=0o700)
        state = {'id':body['id'],'phase':'backing_up','created_at':datetime.now(timezone.utc).isoformat()}
        write_json(directory/'state.json',state)
        try:
            backup = backup_database(directory)
            approved_schedule(body['start_at'], zone)
            fresh = inspect_scope(mes, public)
            if fresh['digest'] != body['digest']:
                raise ResetRefused('MES state changed during backup')
            # From this point a crash/timeout may have persisted changes. Never
            # automatically replay the write or silently accept a second reset.
            state['phase']='archiving'
            write_json(directory/'state.json',state)
            mes.http.headers['X-Demo-Reset-Key'] = os.environ['DEMO_RESET_ARCHIVE_KEY']
            archived = mes.request('POST', '/api/v1/demo/reset-archive', body={
                'orders':fresh['orders'], 'maintenance':fresh['maintenance'],
                'line_ids':[row['id'] for row in fresh['lines']], 'product_id':fresh['product_id']})['data']
            mes.http.headers.pop('X-Demo-Reset-Key',None)
            state['phase']='creating'
            write_json(directory/'state.json',state)
            baseline=[]
            run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+body['id'][:8]

            def call(words):
                result=execute(build_parser().parse_args(words),mes)
                with (directory/'execution.jsonl').open('a',encoding='utf-8') as log:
                    log.write(json.dumps({'command':words,'result':result})+'\n')
                if result.get('verified') is False:
                    raise ResetRefused('OpenMES did not verify the new plan')
                return result

            for index,slot in enumerate(schedule):
                made=call(['order','create','--order-no',f'A4S-381-{run}-{slot["lot"]}',
                    '--line',str(archived['line_id']),'--product-type-id',str(archived['product_id']),
                    '--planned-qty','90','--priority',str(2-index),'--due-date',slot['due_date'],
                    '--description',f'Phone housing lot {slot["lot"]}. 90 units / 45 minute planning slot.'])
                identifier=made['read_back']['data']['id']
                call(['order','accept',str(identifier)])
                call(['schedule','move',str(identifier),'--line',str(archived['line_id']),
                      '--start',slot['planned_start_at'],'--end',slot['planned_end_at']])
                order=call(['order','show',str(identifier)])['data']
                if (order['status']!='ACCEPTED' or order['line_id']!=archived['line_id'] or
                    float(order['planned_qty'])!=90 or float(order['produced_qty'])!=0 or
                    any(datetime.fromisoformat(order[k].replace('Z','+00:00')) !=
                        datetime.fromisoformat(slot[k]) for k in ('planned_start_at','planned_end_at'))):
                    raise ResetRefused('New order read-back differs from the approved plan')
                baseline.append(order)
            final=inspect_scope(mes,public)
            if {o['id'] for o in final['orders']} != {o['id'] for o in baseline} or final['maintenance_count']:
                raise ResetRefused('Reset read-back contains unexpected orders or maintenance')
            manifest={'run_id':run,'started_at':state['created_at'],'ready_at':datetime.now(timezone.utc).isoformat(),
                'mes_endpoint':public,'baseline':baseline,'backup':f'demo-reset:/backups/{body["id"]}/{backup.name}',**archived}
            outcome={'run_id':run,'orders':[{k:o[k] for k in ('id','order_no','planned_start_at','planned_end_at')} for o in baseline],
                'backup':manifest['backup'],'archived_orders':archived['archived_orders'],
                'archived_maintenance':archived['archived_maintenance'],'aas_modified':False}
            result={'manifest':manifest,'outcome':outcome}
            write_json(directory/'result.json',result)
            state['phase']='complete'
            write_json(directory/'state.json',state)
            return result
        except Exception:
            state['phase']='safe_failure' if state['phase']=='backing_up' else 'uncertain'
            write_json(directory/'state.json',state)
            raise


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def reply(self,status,body):
        data=json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply(200 if self.path=='/health' else 404,{'ok':self.path=='/health'})

    def do_POST(self):
        configured=os.environ.get('DEMO_RESET_TOKEN','')
        if len(configured)<32 or not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+configured):
            return self.reply(403,{'error':'Forbidden'})
        if self.path!='/reset':
            return self.reply(404,{'error':'Unknown operation'})
        if not LOCK.acquire(blocking=False):
            return self.reply(409,{'error':'Another reset is running'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<65536:
                raise ResetRefused('Invalid request size')
            body=json.loads(self.rfile.read(length))
            result=perform_reset(body)
            self.reply(200,result)
        except (ResetRefused,ValueError,KeyError,TypeError):
            self.reply(409,{'error':'Reset refused; refresh preview or review the previous reset backup'})
        except Exception:
            self.reply(502,{'error':'Reset failed or is uncertain; inspect the backup before retrying'})
        finally:
            LOCK.release()


def main():
    ThreadingHTTPServer(('0.0.0.0',8093),Handler).serve_forever()


if __name__=='__main__':
    main()
