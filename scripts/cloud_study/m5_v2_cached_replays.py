"""Replay selected frozen evidence on copies; preserve original SQLite bytes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from ega.evaluation.faithfulness import replay, deletion_test, counterfactual

ROOT = Path('/workspace/MasterDissertation')
OUT = ROOT / 'results/v2_pilot'
SCRATCH = Path('/tmp/m5_v2_selected_cached_replays')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(path):
    return {p.relative_to(path).as_posix(): sha(p)
            for p in sorted(path.rglob('*')) if p.is_file()}


if not (OUT / 'execution_complete.json').exists():
    raise RuntimeError('Wait for original evaluation completion')
if SCRATCH.exists() or (OUT / 'selected_cached_replay.json').exists():
    raise FileExistsError('Do not overwrite an existing replay assessment')

SCRATCH.mkdir()
selection = [
    ('parser_no_recovery', 'B4', 'derived_field_collapse', 13, 1862),
    ('parser_recovery', 'B4', 'derived_field_collapse', 13, 1862),
    ('llm_v2_no_recovery', 'B10', 'normal', 13, 1858),
    ('llm_v2_recovery', 'B10', 'derived_field_collapse', 13, 1862),
    ('llm_v2_recovery', 'B10', 'feed_gap', 13, 1862),
]
assessment = {
    'started_at_utc': datetime.now(timezone.utc).isoformat(),
    'mode': 'cached external evidence and deterministic tools; no model calls or forecast retraining',
    'scope': 'Five selected decisions, not all 448. Optimizer is rerun under its frozen five-second limit.',
    'originals_preserved': True,
    'cases': [],
}
for arm, policy, scenario, seed, day in selection:
    run = OUT / arm / f'{policy}__{scenario}__seed{seed}__origin0'
    before = inventory(run)
    copy = SCRATCH / arm / run.name
    shutil.copytree(run, copy)
    record = {'arm': arm, 'scenario': scenario, 'seed': seed, 'day': day,
              'source_run': str(run), 'source_file_hashes': before}
    try:
        record['replay'] = replay(copy, day=day)
        if not record['replay']['held']:
            record['required_forecast_deletion'] = deletion_test(copy, day=day, artifact='forecast')
            if arm == 'llm_v2_no_recovery' and scenario == 'normal':
                record['deterministic_tool_counterfactuals'] = [
                    counterfactual(copy, day=day, factor=factor, multiplier=0.01)
                    for factor in ('budget', 'capacity')
                ]
                record['counterfactual_scope'] = (
                    'Large synthetic intervention on reconstructed optimizer inputs only. '
                    'No model context intervention or neural reasoning attribution. '
                    'Capacity affects supplier availability; a nonbinding factor can leave '
                    'the recorded action unchanged, and a binding factor can induce a hold.'
                )
    except Exception as exc:
        record['assessment_error'] = f'{type(exc).__name__}: {exc}'
    after = inventory(run)
    record['original_source_bytes_unchanged'] = before == after
    assessment['originals_preserved'] &= before == after
    assessment['cases'].append(record)
    print(json.dumps({k: v for k, v in record.items() if k != 'source_file_hashes'}), flush=True)
assessment['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
destination = OUT / 'selected_cached_replay.json'
destination.write_text(json.dumps(assessment, indent=2), encoding='utf8')
if not assessment['originals_preserved']:
    raise RuntimeError('Original bytes changed during assessment')
