"""Verify FreshRetailNet delivery bytes against ordinary Git objects."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / 'study_results/freshretailnet'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git_digest(object_id):
    process = subprocess.Popen(['git', 'cat-file', 'blob', object_id], cwd=ROOT,
                               stdout=subprocess.PIPE)
    checksum = hashlib.sha256(); size = 0
    while block := process.stdout.read(1024 * 1024):
        size += len(block); checksum.update(block)
    if process.wait():
        raise RuntimeError(f'Cannot read Git object: {object_id}')
    return size, checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    info = json.loads((DELIVERY / 'archives.json').read_text())
    expected = {}
    for archive in info['archives'].values():
        for record in archive['parts']:
            expected[record['path']] = record
    expected[info['inventory']['path']] = {'sha256':info['inventory']['sha256']}
    direct = json.loads((DELIVERY / 'direct_delivery_receipt.json').read_text())
    assert direct['status'] == 'VERIFIED'
    expected.update({r['path']:r for r in direct['files']})
    for name, record in expected.items():
        path = DELIVERY / name
        assert digest(path) == record['sha256'], name
        if 'bytes' in record:
            assert path.stat().st_size == record['bytes'], name
    command = ['git', 'ls-files', '-s', '-z'] if args.staged else ['git', 'ls-tree', '-r', '-z', args.ref]
    entries = subprocess.check_output(command, cwd=ROOT).split(b'\0')
    selected = []
    for entry in entries:
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1); name = raw_name.decode()
        if (name.startswith(('study_results/freshretailnet/', 'study_results/dissertation/',
                             'scripts/freshretailnet/', 'src/ega/freshretail/')) or
            name.startswith('tests/test_fresh') or
            name in {'scripts/package_freshretailnet.py', 'scripts/freshretailnet_delivery.py',
                     'scripts/publish_freshretailnet.py', 'scripts/validate_freshretailnet_documents.py',
                     'scripts/verify_freshretailnet_git.py', 'scripts/build_integrated_dissertation.py',
                     'scripts/validate_integrated_dissertation.py', 'study_results/README.md',
                     'study_results/research_context/Evidence_Gated_Autonomy_Dissertation_Revised.docx',
                     'study_results/research_context/Evidence_Gated_Autonomy_M5_FreshRetailNet_Full_Dissertation.docx'}):
            fields = metadata.split()
            object_id = fields[1].decode() if args.staged else fields[2].decode()
            size, checksum = git_digest(object_id); path = ROOT / name
            assert size == path.stat().st_size and checksum == digest(path), name
            assert size <= 100 * 1024 * 1024, f'Git blob exceeds 100 MiB: {name}'
            selected.append({'path':name, 'bytes':size, 'sha256':checksum, 'git_blob':object_id})
    tracked = {r['path'] for r in selected}
    missing = ['study_results/freshretailnet/' + p for p in expected
               if 'study_results/freshretailnet/' + p not in tracked]
    assert not missing, missing
    result = {'status':'VERIFIED', 'verified_at_utc':datetime.now(timezone.utc).isoformat(),
              'git_source':'index' if args.staged else args.ref,
              'files':selected, 'original_bytes_equal_git_blobs':True,
              'archive_parts_verified':sum(len(a['parts']) for a in info['archives'].values()),
              'maximum_git_blob_bytes':max(r['bytes'] for r in selected)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status':result['status'], 'files':len(selected),
                      'maximum_git_blob_bytes':result['maximum_git_blob_bytes']}))


if __name__ == '__main__':
    main()
