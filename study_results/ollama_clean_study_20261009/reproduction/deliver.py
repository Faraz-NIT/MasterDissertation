"""Package the fresh study's complete evidence, with byte-level restoration checks."""
from __future__ import annotations
import hashlib
import json
import shutil
import zipfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'study_results/ollama_clean_study_20261009'
ZIP=OUT/'Fresh_Ollama_Study_download.zip'
EXCLUDE={ZIP.name,'delivery_manifest.json','git_verification.json','publication_receipt.json'}


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    audit=json.loads((OUT/'analysis/audit_receipt.json').read_text())
    documents=json.loads((OUT/'document_receipt.json').read_text())
    if audit['status']!='VERIFIED' or documents['status']!='VERIFIED':
        raise RuntimeError('Audit and documents must pass before delivery')
    for suffix in ('docx','pdf'):
        if sha(OUT/f'Fresh_Ollama_Study_Report.{suffix}')!=documents[f'{suffix}_sha256']:
            raise RuntimeError('Validated document changed')
    # Include snapshots of all new study scripts, alongside the three frozen policy scripts.
    sources=OUT/'reproduction';sources.mkdir(exist_ok=True)
    for path in (ROOT/'scripts/ollama_clean_study').iterdir():
        if path.is_file() and path.suffix in ('.py','.txt'):
            shutil.copyfile(path,sources/path.name)
    shutil.copyfile(ROOT/'tests/test_ollama_clean_study.py',sources/'test_ollama_clean_study.py')
    server=ROOT/'results/ollama_clean_study_20261009/logs/ollama_server.log'
    if server.exists():shutil.copyfile(server,OUT/'logs/ollama_server_snapshot.log')
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name not in EXCLUDE)
    entries=[]
    with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in files:
            if path.stat().st_size>=100*1024**2:raise RuntimeError('Individual file exceeds ordinary Git limit')
            rel=path.relative_to(OUT).as_posix()
            entries.append({'path':rel,'bytes':path.stat().st_size,'sha256':sha(path)})
            z.write(path,rel)
    with zipfile.ZipFile(ZIP) as z:
        if z.testzip():raise RuntimeError('Archive CRC failure')
        if set(z.namelist())!={r['path'] for r in entries}:raise RuntimeError('Archive membership mismatch')
        for entry in entries:
            raw=z.read(entry['path'])
            if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise RuntimeError('Archive bytes differ: '+entry['path'])
    if ZIP.stat().st_size>=100*1024**2:
        raise RuntimeError('Download ZIP exceeds ordinary Git size limit; split before publication')
    manifest={'status':'VERIFIED','at_utc':datetime.now(timezone.utc).isoformat(),'execution_complete':audit['execution_complete'],
        'original_files':len(entries),'uncompressed_bytes':sum(r['bytes'] for r in entries),'files':entries,
        'archive':{'path':ZIP.name,'bytes':ZIP.stat().st_size,'sha256':sha(ZIP)},
        'excluded_self_referential_or_later_receipts':sorted(EXCLUDE),
        'scope':'All new study output files, full raw model requests/responses, decisions, prepared panels, forecast weights, code, development failures, analysis, graphs and reports',
        'excluded_runtime_or_external_assets':['Installed model weights','Installed Ollama binary','Virtual environments','Full cached raw source releases','Authentication or machine secrets']}
    (OUT/'delivery_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ('status','original_files','uncompressed_bytes','archive')}))


if __name__=='__main__':main()
