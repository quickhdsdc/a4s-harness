"""Include the operator-authorized credentials and current demo DB snapshot."""
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

from colleague_paths import ROOT, OUT, ARCHIVE, TAG
PRIVATE=OUT/'private'
PRIVATE.mkdir(exist_ok=True)
def read_env(path):
    values={}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        key,sep,value=raw.strip().partition('=')
        if sep and not key.startswith('#'):
            values[key.removeprefix('export ')]=value.strip().strip("'\"")
    return values
def write_env(path,values):
    assert all('\n' not in v and "'" not in v for v in values.values()),'Unsupported runtime quoting; no values printed'
    path.write_text(''.join(f"{k}='{v}'\n" for k,v in values.items()),encoding='utf-8',newline='\n')
    path.chmod(0o600)
local=read_env(ROOT/'.env');mes=read_env(ROOT/'.env.openmes')
keys_path=PRIVATE/'deployment-keys.json'
if not keys_path.exists():
    keys_path.write_text(json.dumps({k:secrets.token_hex(24) for k in ('mongo','service','archive')}),encoding='utf-8')
keys=json.loads(keys_path.read_text())
backend={k:v for k,v in local.items() if k.startswith(('A4S_','AZURE_','OPENAI_','ANTHROPIC_','Claude_'))}
for key in ('A4S_ENV_FILE','A4S_INDEX_HOME','BACKEND_CONFIG_FILE'):backend.pop(key,None)
backend.update(A4S_AAS_ENDPOINT='http://aas-env:8081',A4S_SMT_ENDPOINT='http://aas-env:8081',
    A4S_MES_ENDPOINT='http://openmes:8000',A4S_MES_UI_URL='http://localhost:8092',
    A4S_MES_TIMEZONE='Europe/Berlin',A4S_DEMO_RESET_URL='http://demo-reset:8093',
    A4S_DEMO_RESET_MES_ENDPOINT='http://openmes:8000',A4S_DEMO_RESET_TOKEN=keys['service'],
    A4S_HOME='/app/records/harness',A4S_WEB_WORKSPACE='/app/temp/harness-web',
    A4S_WEB_WORKDIR='/app/temp/harness-work',A4S_LIVE_MONITOR_DB='/app/records/live-monitor.db',
    A4S_SHELL='/bin/bash')
assert all(backend.get(k) for k in ('A4S_MODEL','A4S_MES_TOKEN')),'Local model or MES configuration missing'
write_env(PRIVATE/'backend.env',backend)
write_env(PRIVATE/'frontend.env',{})
write_env(PRIVATE/'postgres.env',dict(POSTGRES_DB='openmes',POSTGRES_USER='openmes',POSTGRES_PASSWORD=mes['OPENMES_DB_PASSWORD']))
write_env(PRIVATE/'openmes.env',dict(APP_NAME='OpenMES',APP_ENV='production',APP_DEBUG='false',
    APP_KEY=mes['OPENMES_APP_KEY'],APP_TIMEZONE='Europe/Berlin',DB_CONNECTION='pgsql',DB_HOST='postgres',
    DB_DATABASE='openmes',DB_USERNAME='openmes',DB_PASSWORD=mes['OPENMES_DB_PASSWORD'],ADMIN_USERNAME='a4s-admin',
    ADMIN_EMAIL='a4s-admin@example.invalid',ADMIN_PASSWORD=mes['OPENMES_ADMIN_PASSWORD'],
    OPENMES_DEMO_RESET_ENABLED='true',OPENMES_DEMO_RESET_KEY=keys['archive'],LOG_CHANNEL='stderr',
    SESSION_DRIVER='database',QUEUE_CONNECTION='database',BROADCAST_CONNECTION='log'))
write_env(PRIVATE/'demo-reset.env',dict(DEMO_RESET_TOKEN=keys['service'],DEMO_RESET_ARCHIVE_KEY=keys['archive'],
    DEMO_MES_PUBLIC_ENDPOINT='http://openmes:8000',A4S_MES_ENDPOINT='http://openmes:8000',
    A4S_MES_TOKEN='provision-on-first-start',A4S_MES_TIMEZONE='Europe/Berlin',PGHOST='postgres',
    PGUSER='openmes',PGDATABASE='openmes',PGPASSWORD=mes['OPENMES_DB_PASSWORD'],DEMO_RESET_BACKUPS='/backups'))
write_env(OUT/'.env',{'MONGO_PASSWORD':keys['mongo'],'FRONTEND_PORT':'8080','BACKEND_PORT':'8090',
    'MES_PORT':'8092','AAS_PORT':'8081','AAS_REGISTRY_PORT':'8082','SM_REGISTRY_PORT':'8083',
    'DISCOVERY_PORT':'8084','AAS_GUI_PORT':'3000'})
# Original settings are included privately for reference, never echoed.
for source,name in [(ROOT/'.env','workstation.env'),(ROOT/'.env.openmes','workstation-openmes.env')]:
    shutil.copyfile(source,PRIVATE/name)
dump=PRIVATE/'openmes-demo.dump'
with dump.open('wb') as stream:
    subprocess.run(['docker','exec','a4s-openmes-postgres-1','pg_dump','-U','openmes','-d','openmes','-Fc'],stdout=stream,check=True)
assert dump.stat().st_size>1000
(PRIVATE/'LOGIN.txt').write_text('OpenMES: http://localhost:8092\nUsername: a4s-admin\nPassword: '+mes['OPENMES_ADMIN_PASSWORD']+'\n',encoding='utf-8')
for path in PRIVATE.iterdir():path.chmod(0o600)
print('Private runtime configuration and demo database packaged; credential values not printed.')
