"""Create and byte-verify a complete V2 pilot evidence download after reporting."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path('/workspace/MasterDissertation')
PILOT = ROOT / 'results/v2_pilot'
REPORT = ROOT / 'results/v2_pilot/report_final'
EXPORT = ROOT / 'results/v2_report'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


if json.loads((PILOT/'execution_complete.json').read_text())['status'] != 'COMPLETE':
    raise RuntimeError('Original evaluation has not completed')
if json.loads((REPORT/'M5_v2_pilot_report_data.json').read_text())['status'] != 'COMPLETE':
    raise RuntimeError('Independent report audit has not completed')

EXPORT.mkdir(parents=True, exist_ok=True)
members = {}
for folder, prefix in [(PILOT, 'pilot'),
                       (ROOT/'results/v2_report_validation', 'independent_validation'),
                       (ROOT/'data/processed/m5', 'prepared_m5_panel')]:
    for p in sorted(folder.rglob('*')):
        if p.is_symlink():
            raise ValueError(f'Unexpected symlink in frozen evidence: {p}')
        if p.is_file() and p.name != 'M5_v2_results_and_evidence.zip':
            if p.name == 'full_export.stdout.log':
                continue  # Final archive verification output is retained separately.
            # Finished WAL-mode SQLite reads may leave zero-byte WAL and shared
            # memory sidecars. Preserve those original bytes without checkpointing
            # or deleting them. Completion and chain audits already verified the
            # original databases; sidecar presence alone is not an active writer.
            if p.name.endswith('.tmp'):
                raise ValueError(f'Temporary source write is incomplete: {p}')
            members[prefix+'/'+p.relative_to(folder).as_posix()] = p
for p in sorted(Path('/workspace/tools').glob('m5_v2_*.py')):
    members['helpers/'+p.name] = p
for p in sorted(Path('/workspace/tools').glob('m5_v2_*validation*.json')):
    members['helpers/'+p.name] = p
for name in ['pyproject.toml', 'requirements-tested-core.txt', 'README.md']:
    members['repository_metadata/'+name] = ROOT/name
document = ROOT/'results/report/source/dissertation_revised_business_school.html'
members['research_context/'+document.name] = document

records = {name: {'sha256': sha(path), 'bytes': path.stat().st_size}
           for name, path in members.items()}
inventory = {
    'format': 'm5-v2-complete-evidence-export-v1',
    'created_at_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'All V2 development/evaluation content-addressed objects, SQLite audit histories, complete verified grounding cache, request/response and workflow logs, failed and passing software checks, protocol/configurations, frozen source/tests and tracked patch, repository package metadata, prepared 30-series M5 panel, shared trained GRU, report and scientific figures, helper scripts and revised dissertation context.',
    'excluded': ['Model weights', 'Python environment and installed binaries',
                 'Complete raw M5 competition dataset', 'Original historical study artifacts',
                 'Nested compact report ZIP and this ZIP',
                 'Own completed archive-verification receipt/stdout, retained beside the ZIP'],
    'reproduction_limit': 'Relative source snapshots and data are included. Original absolute workspace paths remain in recorded provenance. Reproduction requires dependencies and the pinned local model weights; a fresh environment restore has not been verified.',
    'member_count': len(records),
    'source_bytes': sum(x['bytes'] for x in records.values()),
    'members': records,
}
inventory_bytes = json.dumps(inventory, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False).encode()
manifest = EXPORT/'M5_v2_full_export_inventory.json'
manifest.write_bytes(inventory_bytes)
readme = '''M5 V2 complete pilot evidence

Read pilot/report_final/M5_v2_pilot_report.pdf for methods, findings, graphs and limitations.
The report evidence README describes the smaller companion export; this complete
archive additionally contains every original V2 SQLite history and object store.
The pilot covered all 30 prepared series in 32 runs and 448 decision days.
Use FULL_EXPORT_INVENTORY.json to verify original SHA-256 bytes.
pilot/ includes every raw V2 object and SQLite history, including failed initial
model development and failed test checks before their recorded correction.
pilot/frozen_code/ is the actual evaluated source/test snapshot; the tracked
patch alone omits newly created files. helpers/ contains execution/report code.
prepared_m5_panel/ and pilot/shared/ contain the evaluated data and forecaster.

The local model proposed numeric terms for two bounded supplier/portfolio
clauses. Deterministic parsing supplied the other supported clauses, and tools
bound structural metadata after validation. Cache reuse is not a new model trial.
Recovery used added current simulated source/ledger evidence, shared by all arms.
No general LLM superiority or field performance is established by this pilot.

Model weights, virtual environment and the full raw M5 dataset are excluded.
Absolute source paths in provenance describe the original cloud execution.
Fresh-machine reproduction and restoration have not been independently verified.
'''
destination = EXPORT/'M5_v2_complete_logs_and_evidence.zip'
if destination.exists():
    raise FileExistsError('Preserve existing evidence archives')
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for name, path in sorted(members.items()):
        z.write(path, name)
    z.writestr('FULL_EXPORT_INVENTORY.json', inventory_bytes)
    z.writestr('README.txt', readme)
print(json.dumps({'phase': 'archive_written', 'members': len(records),
                  'source_bytes': inventory['source_bytes'],
                  'archive_bytes': destination.stat().st_size}), flush=True)
with zipfile.ZipFile(destination) as z:
    if len(z.namelist()) != len(set(z.namelist())):
        raise ValueError('Duplicate evidence archive members')
    for name, expected in records.items():
        with z.open(name) as stream:
            actual_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual_sha != expected['sha256'] or z.getinfo(name).file_size != expected['bytes']:
            raise ValueError(f'Export differs from original bytes: {name}')
receipt = {'status': 'VERIFIED', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
           'path': str(destination), 'sha256': sha(destination),
           'bytes': destination.stat().st_size, 'members': len(records),
           'source_bytes': inventory['source_bytes'],
           'inventory_sha256': hashlib.sha256(inventory_bytes).hexdigest()}
(EXPORT/'M5_v2_full_export_receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt), flush=True)
