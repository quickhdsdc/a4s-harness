"""Checksum and assemble the private, operator-authorized deployment archive."""
import hashlib
from pathlib import Path
import zipfile

from colleague_paths import ROOT, OUT, ARCHIVE, TAG
archive=ARCHIVE
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024**2),b''):h.update(part)
    return h.hexdigest()
files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
assert not any(p.name.endswith('.partial') for p in files)
(OUT/'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.relative_to(OUT).as_posix()}\n' for p in files),encoding='utf-8',newline='\n')
with zipfile.ZipFile(archive.with_suffix('.zip.partial'),'w',allowZip64=True) as z:
    for path in sorted(p for p in OUT.rglob('*') if p.is_file()):
        z.write(path,ARCHIVE.stem+'/'+path.relative_to(OUT).as_posix(),
                compress_type=zipfile.ZIP_STORED if path.name=='images-all.tar.gz' else zipfile.ZIP_DEFLATED)
archive.with_suffix('.zip.partial').replace(archive)
archive.with_suffix('.zip.sha256').write_text(digest(archive)+'  '+archive.name+'\n',encoding='utf-8')
print('Complete private archive:',archive,'size MiB:',archive.stat().st_size//1024**2)
