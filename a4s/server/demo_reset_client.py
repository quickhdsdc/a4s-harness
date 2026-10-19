"""Backend access to the configured private reset service; never a user URL."""
import os

import httpx

from ..machines.festo_cp_lab.demo_reset import reset_target
from ..mesctl.client import MesError


def execute_service(preview_id, preview, scope, zone):
    url = reset_target(scope['endpoint'])
    if not url:
        raise MesError('Deployment reset service is not configured')
    with httpx.Client(timeout=httpx.Timeout(600, connect=5), follow_redirects=False) as client:
        response = client.post(url+'/reset', headers={
            'Authorization': 'Bearer '+os.environ['A4S_DEMO_RESET_TOKEN']}, json={
            'id':preview_id, 'digest':preview['digest'], 'endpoint':scope['endpoint'],
            'start_at':preview['start_at'], 'schedule':preview['schedule'], 'timezone':zone})
        if response.status_code != 200:
            raise MesError('Demo reset service refused or could not verify the reset', status=response.status_code)
        data = response.json()
        return data['outcome'], data['manifest']
