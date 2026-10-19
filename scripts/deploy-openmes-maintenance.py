"""Install the local OpenMES maintenance interval API patch; no MES record changes."""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'backend/app/Http/Controllers/Api/V1/MaintenanceEventController.php'
REMOTE = '/var/www/html/' + RELATIVE.removeprefix('backend/')
CONTAINER = 'a4s-openmes-backend-1'


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def main():
    vendor = ROOT / '_others/OpenMes-main'
    patch = ROOT / 'scripts/openmes-maintenance-interval.patch'
    check = subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=vendor, capture_output=True)
    if check.returncode:
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=vendor, check=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=vendor, check=True)
    # Inspect only non-secret identity fields before replacing any file.
    identity = json.loads(run('docker', 'inspect', '--format',
        '{"name":{{json .Name}},"ports":{{json .HostConfig.PortBindings}}}', CONTAINER,
        capture_output=True, text=True).stdout)
    bindings = identity['ports'].get('8000/tcp', [])
    if not any(b['HostIp'] == '127.0.0.1' and b['HostPort'] == '8092' for b in bindings):
        raise RuntimeError('Expected isolated local OpenMES on 127.0.0.1:8092')
    staging = ROOT / 'work/temp/openmes-maintenance' / uuid.uuid4().hex[:10]
    staging.mkdir(parents=True)
    before = staging / 'MaintenanceEventController.before.php'
    run('docker', 'cp', CONTAINER + ':' + REMOTE, str(before))
    source = vendor / RELATIVE
    incoming = '/tmp/a4s-maintenance-interval.php'
    run('docker', 'cp', str(source), CONTAINER + ':' + incoming)
    run('docker', 'exec', CONTAINER, 'php', '-l', incoming)
    try:
        run('docker', 'exec', CONTAINER, 'cp', incoming, REMOTE)
        run('docker', 'exec', CONTAINER, 'php', 'artisan', 'octane:reload')
    except Exception:
        run('docker', 'cp', str(before), CONTAINER + ':' + REMOTE)
        run('docker', 'exec', CONTAINER, 'php', 'artisan', 'octane:reload')
        raise
    result = {'installed': True, 'backup': str(before), 'database_changes': False,
              'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    (staging / 'installation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
