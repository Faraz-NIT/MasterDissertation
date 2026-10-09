"""Monitor the cloud worker and build audited reports after evaluation ends."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'study_results/ollama_clean_study_20261009'


def event(phase,**values):
    row={'at_utc':datetime.now(timezone.utc).isoformat(),'phase':phase,**values}
    print(json.dumps(row),flush=True)
    with (OUT/'logs/supervision.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')


def main():
    env=os.environ.copy();env.update(MPLCONFIGDIR='/tmp/ollama-clean-study-matplotlib',
        XDG_CACHE_HOME='/tmp/ollama-clean-study-cache',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    while not (OUT/'execution_receipt.json').exists():
        lines=(OUT/'logs/execution.log').read_text().splitlines()
        updates=[]
        for line in lines:
            try:
                row=json.loads(line)
                if row.get('phase')=='case_complete':updates.append(row)
            except json.JSONDecodeError:pass
        last=updates[-1] if updates else {}
        current=json.loads((OUT/'progress.json').read_text()) if (OUT/'progress.json').exists() else {}
        event('running',runs_complete=last.get('runs_complete',0),expected_runs=1080,
            fresh_calls_complete=last.get('fresh_calls',0),current_case=current.get('case'),day=current.get('day_completed'))
        process=json.loads((OUT/'execution_process.json').read_text())['pid']
        status=Path(f'/proc/{process}/stat')
        if not status.exists() or status.read_text().split()[2]=='Z':
            event('worker_stopped_without_completion_receipt');raise RuntimeError('Study worker stopped; preserve and investigate logs')
        time.sleep(40)
    receipt=json.loads((OUT/'execution_receipt.json').read_text());event('evaluation_finished',**receipt)
    phases=[('audit',[str(ROOT/'.venv/bin/python'),'scripts/ollama_clean_study/analyze.py']),
            ('reports',[sys.executable,'scripts/ollama_clean_study/report.py'])]
    if receipt['status']!='COMPLETE':phases[0][1].append('--allow-partial')
    for name,command in phases:
        event(name+'_started')
        with (OUT/'logs'/f'{name}.log').open('a') as log:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            event(name+'_failed',exit_code=result.returncode);raise RuntimeError(name+' failed; inspect preserved log')
        event(name+'_complete')
    event('ready_for_visual_review_and_publication')


if __name__=='__main__':main()
