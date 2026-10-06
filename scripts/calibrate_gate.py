"""Propose gate caps from gate inputs logged on clean-evidence days.

Run a policy with the cap under study disabled (configs/gate_calibration.yaml), then set each
cap at a high quantile of its clean-day distribution: on clean evidence the gate then trips on
roughly (1 - quantile) of days, and faults are left to the state certificate.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

INPUTS = {'spend_deviation': 'max_spend_deviation', 'spend': 'max_spend',
          'max_days_supply': 'max_days_supply', 'forecast_dispersion': 'max_dispersion'}
LEGACY = 'baseline_deviation'  # gate v1 unit ratio, reported for comparison only

def _artifact(run: Path, ref: str):
    return json.loads((run/'artifacts'/'objects'/f'{ref}.json').read_text())

def gate_inputs(results: Path) -> dict[str, list[float]]:
    """Logged gate inputs of every evaluated clean decision. Traces written before gate v2 lack spend_deviation; it is
    recomputed exactly from the stored problem and proposed plan."""
    from ega.autonomy import gate_measures
    from ega.schemas import Plan
    values = {k: [] for k in [*INPUTS, LEGACY]}
    for run in sorted(results.glob('*__*__seed*__origin*')):
        if not (run/'trace_index.json').exists(): continue  # run still in progress
        for entry in json.loads((run/'trace_index.json').read_text()):
            trace = _artifact(run, entry['trace_ref'])
            inputs = trace['autonomy'].get('inputs', {})
            if LEGACY not in inputs: continue  # hard fail or no plan: gate never evaluated
            if 'spend_deviation' not in inputs:
                refs = trace['references']
                inputs = {**inputs, **gate_measures(Plan.model_validate(_artifact(run, refs['propose'])), _artifact(run, refs['problem']))}
            for k in values: values[k].append(float(inputs[k]))
    return values

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', default='results/gate_calibration')
    ap.add_argument('--quantile', type=float, default=0.95)
    ap.add_argument('--out', default='results/gate_calibration/proposed_gate.json')
    a = ap.parse_args()
    values = gate_inputs(Path(a.results))
    n = len(values['spend_deviation'])
    if not n: raise SystemExit(f'No evaluated gate decisions under {a.results}')
    report = {'results': a.results, 'decisions': n, 'quantile': a.quantile, 'caps': {}, 'distribution': {}}
    for k in [*INPUTS, LEGACY]:
        v = np.asarray(values[k])
        report['distribution'][k] = {q: round(float(np.quantile(v, q)), 4) for q in [0.5, 0.75, 0.9, 0.95, 0.99]}
        if k in INPUTS: report['caps'][INPUTS[k]] = round(float(np.quantile(v, a.quantile)), 4)
    Path(a.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
