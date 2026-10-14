"""Monitor a detached cloud run and build audited chapter artifacts when it completes."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'study_results/architecture_study_20261013'


def event(stage, **payload):
    row = {'at_utc': datetime.now(timezone.utc).isoformat(), 'stage': stage, **payload}
    with (OUT / 'logs/supervision.jsonl').open('a') as stream:
        stream.write(json.dumps(row)+'\n')
    print(json.dumps(row), flush=True)


def main():
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               MPLCONFIGDIR='/tmp/architecture-study-matplotlib', XDG_CACHE_HOME='/tmp/architecture-study-cache',
               LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    while not (OUT / 'execution_receipt.json').exists():
        progress = json.loads((OUT / 'progress.json').read_text()) if (OUT / 'progress.json').exists() else {}
        seeds = json.loads((OUT / 'seed_progress.json').read_text()) if (OUT / 'seed_progress.json').exists() else {}
        event('running', runs_complete=seeds.get('runs_complete',0), expected_runs=1080,
              case=progress.get('case'), day=progress.get('day_completed'))
        pid = json.loads((OUT / 'execution_process.json').read_text())['pid']
        stat = Path(f'/proc/{pid}/stat')
        if not stat.exists() or stat.read_text().split()[2] == 'Z':
            event('worker_failed_without_receipt')
            raise RuntimeError('Inspect and preserve worker logs; do not silently restart')
        time.sleep(40)
    receipt = json.loads((OUT / 'execution_receipt.json').read_text())
    event('execution_finished', status=receipt['status'], runs=receipt['runs'])
    if receipt['status'] != 'COMPLETE':
        raise RuntimeError('Registered grid incomplete; never label the chapter as a complete study')
    commands = [
        ('audit_and_analysis', [str(ROOT / '.venv/bin/python'), 'scripts/architecture_study/analyze.py']),
        ('figures', [sys.executable, 'scripts/architecture_study/figures.py']),
        ('chapter', [sys.executable, 'scripts/architecture_study/report.py']),
        ('pdf', ['/opt/codex/runtimes/codex-primary-runtime/dependencies/bin/override/soffice',
                 '-env:UserInstallation=file:///tmp/architecture-study-office', '--headless', '--convert-to', 'pdf',
                 '--outdir', str(OUT), str(OUT / 'Selective_Agent_Architecture_Chapter.docx')]),
    ]
    for stage, command in commands:
        event(stage+'_started')
        with (OUT / 'logs' / (stage+'.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            event(stage+'_failed', returncode=result.returncode)
            raise RuntimeError(stage+' failed; inspect the preserved log')
        event(stage+'_complete')
    (OUT / 'ready_for_review.json').write_text(json.dumps({'status':'READY_FOR_REVIEW',
        'at_utc':datetime.now(timezone.utc).isoformat(),'scope':'One illustrated chapter; no full-dissertation rebuild'},indent=2)+'\n')
    event('ready_for_document_checks_visual_review_and_publication')


if __name__ == '__main__':
    main()
