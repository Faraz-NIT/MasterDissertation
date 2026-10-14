"""Preserve every study output and helper in a verified ZIP, without publishing model weights."""
from pathlib import Path
import gzip
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'study_results/architecture_study_20261013'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package():
    checks = json.loads((OUT/'document_validation.json').read_text())
    assert checks['status'] == 'PASS' and checks['visual_review'].startswith('PASS')
    assert json.loads((OUT/'execution_receipt.json').read_text())['status'] == 'COMPLETE'
    sources = sorted(p for p in (ROOT/'scripts/architecture_study').iterdir() if p.is_file())
    sources += [ROOT/'scripts/ollama_clean_study/core.py', ROOT/'scripts/ollama_clean_study/analyze.py',
                ROOT/'tests/test_selective_architecture.py', ROOT/'tests/test_ollama_clean_study.py']
    reproduction = OUT/'reproduction'
    for source in sources:
        target = reproduction/source.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    archive = OUT/'Selective_Architecture_Complete_Evidence.zip'
    if archive.exists():
        raise FileExistsError('Preserve the existing complete export')
    excluded = {'delivery_manifest.json','file_inventory.json.gz','publication_manifest.json'}
    files = sorted(p for p in OUT.rglob('*') if p.is_file() and p.name not in excluded
                   and not p.name.endswith(('.zip','.pending','.pyc')) and '__pycache__' not in p.parts)
    entries = []
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in files:
            relative = str(path.relative_to(OUT))
            before = sha(path)
            bundle.write(path,relative)
            assert sha(path) == before, 'A file changed while archiving: '+relative
            entries.append({'path':relative,'bytes':path.stat().st_size,'sha256':before})
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for entry in entries:
            content = bundle.read(entry['path'])
            assert len(content)==entry['bytes'] and hashlib.sha256(content).hexdigest()==entry['sha256']
    with gzip.open(OUT/'file_inventory.json.gz','wt',encoding='utf-8') as stream:
        json.dump({'files':entries},stream,separators=(',',':'))
    manifest = {'status':'VERIFIED','scope':'Complete single-chapter architecture study and all native logs',
                'original_files':len(entries),'original_bytes':sum(r['bytes'] for r in entries),
                'archive':{'path':archive.name,'bytes':archive.stat().st_size,'sha256':sha(archive)},
                'inventory_sha256':sha(OUT/'file_inventory.json.gz'),
                'excluded':'LLM weights, raw complete publisher datasets, credentials and runtime caches',
                'all_output_bytes_preserved_and_verified':True}
    assert archive.stat().st_size < 100*1024**2,'Split the complete export before Git publication'
    (OUT/'delivery_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':
    package()
