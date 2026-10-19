"""Export every Compose image into one offline, credential-free release."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from colleague_paths import ROOT, OUT, ARCHIVE, TAG
from colleague_image_identity import archive_identities
compose=json.loads((OUT/'compose.yml').read_text())
images=list(dict.fromkeys(s['image'] for s in compose['services'].values()))
inventory=[]
for name in images:
    info=json.loads(subprocess.check_output(['docker','image','inspect',name]))[0]
    assert info['Architecture']=='amd64' and info['Os']=='linux'
    inventory.append(dict(image=name,id=info['Id'],size=info['Size']))
destination=OUT/'images-all.tar.gz'
process=subprocess.Popen(['docker','save','--platform','linux/amd64',*images],stdout=subprocess.PIPE)
try:
    with gzip.open(destination.with_suffix('.gz.partial'),'wb',compresslevel=1) as out:
        shutil.copyfileobj(process.stdout,out,1024**2)
    assert process.wait()==0,'Image export failed'
    destination.with_suffix('.gz.partial').replace(destination)
finally:
    process.stdout.close()
    if process.poll() is None: process.terminate()
inventory = archive_identities(destination, inventory)
(OUT/'release.json').write_text(json.dumps({'platform':'linux/amd64','images':inventory,
    'database':'read-only snapshot of the current local OpenMES demo; restore only into an empty database',
    'credentials':'existing API keys and MES login included under private, explicitly authorized by the operator'},indent=2)+'\n',encoding='utf-8',newline='\n')
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()
files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
assert (OUT/'private/backend.env').is_file() and (OUT/'private/openmes-demo.dump').is_file()
(OUT/'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.relative_to(OUT).as_posix()}\n' for p in files),encoding='utf-8',newline='\n')
print('Exported',len(images),'images;',destination.stat().st_size//1024**2,'MiB')
