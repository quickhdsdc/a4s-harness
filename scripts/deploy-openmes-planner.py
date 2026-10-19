"""Build and install the local Planner UI fix without changing MES records."""
import json
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    vendor = ROOT / '_others/OpenMes-main'
    patch = ROOT / 'scripts/openmes-planner-dates.patch'
    # Preserve the change even though the downloaded upstream tree is ignored.
    check = subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)],
                           cwd=vendor, capture_output=True)
    if check.returncode:
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=vendor, check=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=vendor, check=True)
    run('docker', 'build', '-f', 'scripts/openmes-planner-ui.Dockerfile',
        '-t', 'a4s-openmes-planner-ui', '_others/OpenMes-main')
    token = uuid.uuid4().hex[:10]
    staging = ROOT / 'work/temp/openmes-planner' / token
    staging.mkdir(parents=True)
    run('docker', 'cp', 'a4s-openmes-backend-1:/var/www/html/public/build', str(staging / 'before'))
    container = 'a4s-planner-assets-' + token
    run('docker', 'create', '--name', container, 'a4s-openmes-planner-ui')
    try:
        run('docker', 'cp', container + ':/var/www/html/public/build', str(staging / 'after'))
    finally:
        run('docker', 'rm', container)
    run('docker', 'cp', str(staging / 'after') + '/.', 'a4s-openmes-backend-1:/var/www/html/public/build')
    run('docker', 'exec', 'a4s-openmes-backend-1', 'php', 'artisan', 'octane:reload')
    print(json.dumps({'installed': True, 'backup': str(staging / 'before'),
                      'build': str(staging / 'after'), 'database_changes': False}))


if __name__ == '__main__':
    main()
