"""Verify staged Git blob bytes and publish only the fresh study's authorized files."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'study_results/ollama_clean_study_20261009'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def main(publish=False):
    manifest=json.loads((OUT/'delivery_manifest.json').read_text())
    if manifest['status']!='VERIFIED':raise RuntimeError('Delivery must be verified first')
    relative=OUT.relative_to(ROOT)
    paths=[relative/entry['path'] for entry in manifest['files']]
    paths.extend([relative/'delivery_manifest.json',relative/manifest['archive']['path'],Path('study_results/README.md'),Path('tests/test_ollama_clean_study.py')])
    paths.extend(p.relative_to(ROOT) for p in (ROOT/'scripts/ollama_clean_study').iterdir() if p.is_file() and p.suffix in ('.py','.txt'))
    task_paths=Path('/tmp/ollama-clean-study-git-paths')
    task_paths.write_bytes(b'\0'.join(str(p).encode() for p in paths)+b'\0')
    git('add','-f','--pathspec-from-file='+str(task_paths),'--pathspec-file-nul')
    names=[name for name in git('diff','--cached','--name-only','-z').decode().split('\0') if name]
    allowed={'study_results/README.md','tests/test_ollama_clean_study.py'}
    for name in names:
        if name not in allowed and not name.startswith('scripts/ollama_clean_study/') and not name.startswith(str(relative)+'/'):
            raise RuntimeError('Unrelated pre-existing staged work must remain separate: '+name)
    entries=[]
    process=subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for name in names:
            process.stdin.write((':'+name+'\n').encode());process.stdin.flush()
            header=process.stdout.readline().decode().split()
            if len(header)!=3 or header[1]!='blob':raise RuntimeError('Missing staged blob '+name)
            size=int(header[2]);raw=process.stdout.read(size);terminator=process.stdout.read(1)
            if terminator!=b'\n' or raw!=(ROOT/name).read_bytes():raise RuntimeError('Git bytes differ '+name)
            if size>=100*1024**2:raise RuntimeError('Git file size limit '+name)
            entries.append({'path':name,'bytes':size,'sha256':hashlib.sha256(raw).hexdigest()})
    finally:
        process.stdin.close();process.wait(timeout=30)
    expected={str(relative/entry['path']):entry for entry in manifest['files']}
    expected[str(relative/manifest['archive']['path'])]=manifest['archive']
    verified={entry['path']:entry for entry in entries}
    for name,item in expected.items():
        if name not in verified or verified[name]['sha256']!=item['sha256'] or verified[name]['bytes']!=item['bytes']:
            raise RuntimeError('Delivery manifest differs from staged bytes '+name)
    receipt={'status':'VERIFIED','at_utc':datetime.now(timezone.utc).isoformat(),
        'parent_commit':git('rev-parse','HEAD').decode().strip(),'staged_files_verified':len(entries),
        'scope':'All new staged study files, complete logs and download archive; this receipt excluded from its own hash list',
        'files':entries}
    file=OUT/'git_verification.json';file.write_text(json.dumps(receipt,indent=2)+'\n')
    git('add','-f',str(file.relative_to(ROOT)))
    if git('cat-file','blob',':'+str(file.relative_to(ROOT)))!=file.read_bytes():raise RuntimeError('Receipt differs in Git')
    subprocess.run(['git','diff','--cached','--check','--','scripts/ollama_clean_study','tests/test_ollama_clean_study.py','study_results/README.md',str(relative/'README.md')],cwd=ROOT,check=True)
    print(json.dumps({'staging':'VERIFIED','files':len(entries)+1,'bytes':sum(r['bytes'] for r in entries)}),flush=True)
    if not publish:return
    subprocess.run(['git','fetch','origin','main'],cwd=ROOT,check=True)
    subprocess.run(['git','merge-base','--is-ancestor','refs/remotes/origin/main','HEAD'],cwd=ROOT,check=True)
    subprocess.run(['git','commit','--quiet','-m','Complete fresh no-repair Ollama agent study on M5 and RetailNet'],cwd=ROOT,check=True)
    subprocess.run(['git','push','origin','HEAD:refs/heads/main'],cwd=ROOT,check=True)
    head=git('rev-parse','HEAD').decode().strip();remote=git('ls-remote','origin','refs/heads/main').decode().split()[0]
    if head!=remote:raise RuntimeError('Remote main does not match published commit')
    status=git('status','--porcelain').decode()
    if status:raise RuntimeError('Uncommitted work remains after publication: '+status)
    print(json.dumps({'publication':'VERIFIED','commit':head,'remote_main_matches':True,'working_tree_clean':True}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    main(args.publish)
