"""Root completion and immutable input audit. Does not alter original run files."""
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import urllib.request

ROOT = Path('/workspace/MasterDissertation')
OUT = ROOT/'results/v2_pilot'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


protocol = json.loads((OUT/'protocol.json').read_text())
complete = json.loads((OUT/'execution_complete.json').read_text())
owner = json.loads((OUT/'supervisor.json').read_text())
assert complete['status'] == 'COMPLETE' and owner['phase'] == 'completed'
assert owner['child_exit_code'] == 0
assert complete['protocol_sha256'] == sha(OUT/'protocol.json')
proof = {'status': 'VERIFIED', 'audited_at_utc': datetime.now(timezone.utc).isoformat(),
         'execution_complete_sha256': sha(OUT/'execution_complete.json'),
         'protocol_sha256': sha(OUT/'protocol.json'),
         'scope': 'Exact registered completion, frozen inputs, workflow/decision chains, usage, shared model and protected original dissertation/report. Independent source accuracy is assessed separately.',
         'frozen_inputs': [], 'arms': []}
for group in ['frozen_source_sha256', 'frozen_prepared_data_sha256', 'frozen_helper_sha256']:
    for name, expected in protocol[group].items():
        p = Path(name) if name.startswith('/') else ROOT/name
        assert sha(p) == expected, str(p)
        proof['frozen_inputs'].append({'group': group, 'path': str(p), 'sha256': expected})
for arm, config_pin in protocol['configs'].items():
    assert sha(config_pin['path']) == config_pin['sha256']
    cfg = json.loads(Path(config_pin['path']).read_text())
    stage = Path(protocol['evaluation']['arms'][arm]['root'])
    expected = set(itertools.product(cfg['policies'], cfg['scenarios'], cfg['seeds'],
                                     range(cfg['origins'])))
    actual = set(); calls = tokens = errors = decisions = violations = held = 0
    for summary_path in sorted(stage.glob('*/summary.json')):
        run = summary_path.parent; summary = json.loads(summary_path.read_text())
        actual.add((summary['policy'], summary['scenario'], summary['seed'], summary['origin']))
        index = json.loads((run/'trace_index.json').read_text())
        assert len(index) == cfg['days'] == summary['trace_count']
        assert sorted(x['day'] for x in index) == list(range(cfg['start_day'], cfg['start_day']+cfg['days']))
        db = sqlite3.connect('file:'+str((run/'artifacts/audit.sqlite').resolve())+'?mode=ro', uri=True)
        previous = '0'*64; events = 0
        for decision, stage_name, payload, prev, event_hash in db.execute('SELECT decision_id,stage,payload,previous_hash,event_hash FROM events ORDER BY seq'):
            obj = {'decision_id': decision, 'stage': stage_name, 'payload': json.loads(payload),
                   'previous_hash': prev}
            assert prev == previous and hashlib.sha256(canonical(obj)).hexdigest() == event_hash
            previous = event_hash; events += 1
        db.close()
        assert summary['chain_valid']
        decisions += len(index); calls += summary['llm_calls']; tokens += summary['tokens']
        errors += summary['llm_errors']; violations += summary['hard_violations']; held += summary['held_decisions']
    assert actual == expected and len(actual) == 8
    common = json.loads((stage/'shared_model_reference.json').read_text())
    assert sha(common['path']) == common['sha256']
    proof['arms'].append({'arm': arm, 'runs': len(actual), 'decision_days': decisions,
                          'calls': calls, 'tokens': tokens, 'errors': errors,
                          'committed_plan_violations': violations, 'held_days': held,
                          'shared_forecast_sha256': common['sha256']})
assert len({a['shared_forecast_sha256'] for a in proof['arms']}) == 1
proof['totals'] = {k: sum(a[k] for a in proof['arms']) for k in
                   ['runs', 'decision_days', 'calls', 'tokens', 'errors',
                    'committed_plan_violations', 'held_days']}
assert proof['totals']['runs'] == complete['runs'] == 32
assert proof['totals']['decision_days'] == complete['decisions'] == 448
assert proof['totals']['calls'] == complete['API_usage']['calls']
previous = '0'*64; n = 0
for line in (OUT/'work_log.jsonl').read_text().splitlines():
    row = json.loads(line); event_hash = row.pop('hash')
    assert row['previous_hash'] == previous and hashlib.sha256(canonical(row)).hexdigest() == event_hash
    previous = event_hash; n += 1
proof['workflow_audit'] = {'records': n, 'final_hash': previous, 'sha256': sha(OUT/'work_log.jsonl')}
protected = {
    'results/report/M5_six_hour_study_report.pdf': 'e3aab72f8bbe2eced7b4b54cd3630eace763d1521cc464711554d5ad1dc298ba',
    'results/report/source/dissertation_revised_business_school.html': '8ae699667fa02f932f4c2584af0a3895021dc925e3119412bb06b238dc87de1c',
}
proof['protected_originals'] = []
for name, expected in protected.items():
    assert sha(ROOT/name) == expected
    proof['protected_originals'].append({'path': name, 'sha256': expected})
with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=30) as response:
    current = json.load(response)
selected = next(m for m in current['models'] if m['name'] == protocol['selected_model']['name'])
assert selected['digest'] == protocol['selected_model']['digest']
proof['selected_model'] = selected
completed_at = datetime.fromisoformat(complete['completed_at_utc'])
requested_at = datetime.fromisoformat(protocol['requested_at_utc'])
proof['elapsed_request_to_evaluation_completion_minutes'] = (completed_at-requested_at).total_seconds()/60
proof['completed_before_cutoff'] = completed_at < datetime.fromisoformat(protocol['experiment_cutoff_utc'])
assert proof['completed_before_cutoff']
proof['code_state'] = 'User-authorized local V2 changes are uncommitted; frozen source/test export, tracked patch and original base commit are preserved. No remote push or fresh environment restoration is claimed.'
(OUT/'final_audit.json').write_text(json.dumps(proof, indent=2), encoding='utf8')
print(json.dumps({k:v for k,v in proof.items() if k != 'frozen_inputs'}, indent=2))
