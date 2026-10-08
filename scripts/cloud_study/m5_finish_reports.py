#!/usr/bin/env python3
"""Refresh reports and repair completed merges without retraining live workers."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/workspace/MasterDissertation')
PY = ROOT / '.venv/bin/python'
STATUS = ROOT / 'results/run_configs/pipeline_status.json'
GENERATOR = ROOT / 'results/report/generate_report.py'


def alive(pid):
    try:
        return bool(Path(f'/proc/{pid}/cmdline').read_bytes())
    except FileNotFoundError:
        return False


def snapshot():
    value = json.loads(STATUS.read_text())
    counts = {}
    for name, stage in value['stages'].items():
        output = Path(stage.get('output', 'results/' + name))
        if not output.is_absolute():
            output = ROOT / output
        worker_root = output.with_name(output.name + '_workers')
        paths = list(worker_root.glob('w*/*/summary.json')) if worker_root.exists() else list(output.glob('*/summary.json'))
        counts[name] = len(paths)
        if name in ['main_study_stage1', 'llm_prose_study_reference']:
            target = stage.get('expected_runs')
            state = stage.get('state', stage.get('status'))
            # Older driver instances retain a faulty manifest check in memory.
            # Completed workers are retained; use the corrected, tested merge-only path.
            if target and len(paths) == target and state != 'complete' and not any(alive(p) for p in stage.get('worker_pids', [])):
                cfg = stage.get('config', stage.get('config_path'))
                command = [str(PY), '/workspace/tools/m5_parallel.py', '--config', str(cfg),
                           '--workers', str(stage.get('workers', 1)), '--stage', name, '--merge-only']
                with (ROOT/'results/logs'/f'{name}_merge_recovery.log').open('a') as log:
                    result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError(f'{name}: merge-only failed; inspect merge recovery log')
    counts['baseline_pilot'] = len(list((ROOT/'results/baseline_pilot').glob('*/summary.json')))
    return value, counts


def refresh():
    with GENERATOR.with_name('refresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with (ROOT/'results/logs/combined_report_refresh.log').open('a') as log:
            subprocess.run([str(PY), str(GENERATOR)], cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    previous = None
    with (ROOT/'results/logs/report_watcher.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            value, counts = snapshot()
            if counts != previous:
                refresh()
                print(json.dumps(counts), flush=True)
                previous = counts
            if args.once:
                return 0
            # The new agentic driver refreshes after its own successful stages.
            # This watcher need not run forever when local model access is blocked.
            baseline_done = counts['baseline_pilot'] == 16
            independent_done = all(value['stages'][s].get('state') == 'complete'
                for s in ['main_study_stage1', 'llm_prose_study_reference'])
            if baseline_done and independent_done:
                refresh()
                return 0
            time.sleep(60)


if __name__ == '__main__':
    raise SystemExit(main())
