"""Merge the per-worker folders written by scripts/run_main_study.sh into one study folder and summarise it.

python scripts/merge_studies.py --config configs/main_study_stage1.yaml \
    --workers results/main_study_stage1_workers --out results/main_study_stage1
Completed run folders are hard-linked (no extra disk, workers stay intact for resuming); partial runs are skipped and
counted. The merged folder gets the full study's resolved_config.json, summary.csv and study_summary.json.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
from pathlib import Path
import pandas as pd
from ega.config import load_config
from ega.experiment import summarize_study, environment
from ega.util import atomic_json

def merge(config_path, workers, out):
    config = load_config(config_path); out = Path(out); out.mkdir(parents=True, exist_ok=True)
    rows = []; partial = 0; first = None
    for w in sorted(Path(workers).glob('w*')):
        if first is None and (w/'resolved_config.json').exists(): first = w
        for run in sorted(w.glob('*__*__seed*__origin*')):
            if not (run/'summary.json').exists(): partial += 1; continue
            dest = out/run.name
            if dest.exists(): shutil.rmtree(dest)
            shutil.copytree(run, dest, copy_function=os.link)
            s = json.loads((run/'summary.json').read_text()); s['path'] = str(dest); rows.append(s)
    if not rows: raise SystemExit(f'No completed runs under {workers}')
    if first is not None:
        for f in first.glob('model_*'):
            if not (out/f.name).exists(): os.link(f, out/f.name)
    atomic_json(out/'resolved_config.json', config); atomic_json(out/'environment.json', environment())
    pd.DataFrame(rows).to_csv(out/'summary.csv', index=False)
    summarize_study(out, config)
    expected = len(config.policies)*len(config.scenarios)*len(config.seeds)*config.origins
    atomic_json(out/'merge_manifest.json', {'workers': str(workers), 'runs_merged': len(rows), 'runs_expected': expected,
                                            'partial_runs_skipped': partial})
    return len(rows), expected, partial

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True); ap.add_argument('--workers', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    n, expected, partial = merge(a.config, a.workers, a.out)
    print(f'{n}/{expected} runs merged into {a.out} ({partial} partial skipped)')
