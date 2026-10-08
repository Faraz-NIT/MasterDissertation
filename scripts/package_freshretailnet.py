"""Archive every completed FreshRetailNet evidence file for ordinary Git."""
from datetime import datetime,timezone
import gzip,hashlib,json
from pathlib import Path
import tempfile,zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'results/freshretailnet'
OUT=ROOT/'study_results/freshretailnet'
PART_BYTES=48*1024*1024

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    assert json.loads((SOURCE/'numerical/execution_complete.json').read_text())['status']=='COMPLETE'
    assert json.loads((SOURCE/'agents/execution_complete.json').read_text())['status']=='COMPLETE'
    assert json.loads((SOURCE/'audit/audit.json').read_text())['status']=='VERIFIED_COMPLETE'
    assert json.loads((SOURCE/'forecast/independent_audit.json').read_text())['status']=='verified'
    assert json.loads((SOURCE/'development/policy_sensitivity_independent_audit.json').read_text())['status']=='VERIFIED'
    assert json.loads((SOURCE/'report/report_manifest.json').read_text())['status']=='VERIFIED'
    assert json.loads((SOURCE/'report/document_integrity_receipt.json').read_text())['status']=='VERIFIED'
    if (SOURCE/'gate_transfer').exists():
        assert json.loads((SOURCE/'gate_transfer/execution_complete.json').read_text())['status']=='COMPLETE'
        assert json.loads((SOURCE/'gate_transfer/audit.json').read_text())['status']=='VERIFIED'
        assert json.loads((SOURCE/'gate_transfer/audit_independent/audit.json').read_text())['status']=='VERIFIED_COMPLETE'
    parts=OUT/'archive_parts';parts.mkdir(parents=True,exist_ok=False)
    candidates=[]
    for folder in [SOURCE,ROOT/'data/raw/freshretailnet',ROOT/'data/processed/freshretailnet',ROOT/'scripts/freshretailnet',ROOT/'src/ega/freshretail']:
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():raise ValueError(f'Evidence symlink refused:{path}')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':candidates.append((path.relative_to(ROOT).as_posix(),path))
    for path in sorted((ROOT/'tests').glob('test_fresh*.py')):candidates.append((path.relative_to(ROOT).as_posix(),path))
    for name in ['scripts/package_freshretailnet.py','scripts/freshretailnet_delivery.py',
                 'scripts/publish_freshretailnet.py','scripts/validate_freshretailnet_documents.py',
                 'scripts/verify_freshretailnet_git.py']:
        candidates.append((name,ROOT/name))
    records=[];dedup={}
    with tempfile.TemporaryDirectory(prefix='fresh-evidence-',dir='/tmp') as temporary:
        packed=Path(temporary)/'FreshRetailNet_complete_evidence.zip'
        with zipfile.ZipFile(packed,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
            for i,(relative,path) in enumerate(candidates,1):
                checksum=sha(path);size=path.stat().st_size;key=(checksum,size)
                if key not in dedup:dedup[key]=relative;archive.write(path,relative)
                records.append({'path':relative,'bytes':size,'sha256':checksum,'archive':'complete','member':dedup[key]})
                if i%10000==0:print(json.dumps({'phase':'inventory','files':i}),flush=True)
        with zipfile.ZipFile(packed) as archive:
            for (checksum,size),member in dedup.items():
                with archive.open(member) as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
                if actual!=checksum or archive.getinfo(member).file_size!=size:raise ValueError(f'Archive changed original bytes:{member}')
        entry={'filename':packed.name,'bytes':packed.stat().st_size,'sha256':sha(packed),'parts':[]};joined=hashlib.sha256()
        with packed.open('rb') as stream:
            number=0
            while block:=stream.read(PART_BYTES):
                number+=1;relative=f'archive_parts/complete.zip.part{number:03d}';path=OUT/relative;path.write_bytes(block);checksum=sha(path);assert checksum==hashlib.sha256(block).hexdigest();joined.update(block)
                entry['parts'].append({'path':relative,'bytes':len(block),'sha256':checksum})
        assert joined.hexdigest()==entry['sha256']
    inventory={'format':'freshretailnet-complete-path-inventory-v1','files':records};path=OUT/'file_inventory.json.gz';path.write_bytes(gzip.compress(json.dumps(inventory,separators=(',',':'),sort_keys=True).encode(),compresslevel=6,mtime=0))
    info={'format':'freshretailnet-git-delivery-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Every FreshRetailNet results file, complete pinned public raw release, prepared30-series panel, frozen models, traces, requests/responses, audits, development failures, reporting sources and tests','license':'Dingdong-Inc/FreshRetailNet-50K CC-BY-4.0; publisher attribution/source revisions in research/','excluded':['Ollama model weights and runtime binaries','Virtual environment','Authentication files and compiled/runtime caches outside the study'],'archives':{'complete':entry},'inventory':{'path':path.name,'sha256':sha(path),'files':len(records),'source_bytes':sum(r['bytes'] for r in records)}}
    (OUT/'archives.json').write_text(json.dumps(info,indent=2)+'\n')
    receipt={'status':'VERIFIED','source_files':len(records),'unique_archive_members':len(dedup),'source_bytes':info['inventory']['source_bytes'],'archive_bytes':entry['bytes'],'parts':len(entry['parts']),'maximum_part_bytes':max(p['bytes'] for p in entry['parts']),'archive_sha256':entry['sha256']}
    (OUT/'packaging_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)

if __name__=='__main__':main()
