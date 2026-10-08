"""Check recovery narrative against original run means and misleading contrasts."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path('/workspace/MasterDissertation')
PILOT = ROOT/'results/v2_pilot'
spec = importlib.util.spec_from_file_location('v2_report', '/workspace/tools/m5_v2_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
data_path = PILOT/'report_final/M5_v2_pilot_report_data.json'
data = json.loads(data_path.read_text())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def mean(arm, key):
    rows = [json.loads(p.read_text()) for p in (PILOT/arm).glob('B10__derived_field_collapse__*/summary.json')]
    assert len(rows) == 2
    return sum(r[key] for r in rows)/len(rows)


before_cost = mean('llm_v2_no_recovery', 'cost')
after_cost = mean('llm_v2_recovery', 'cost')
before_fill = mean('llm_v2_no_recovery', 'fill_rate')
after_fill = mean('llm_v2_recovery', 'fill_rate')
expected = [f'from {before_cost:.2f} to {after_cost:.2f} USD',
            f'({100*(after_cost-before_cost)/before_cost:+.2f}%)',
            f'from {before_fill*100:.1f}% to {after_fill*100:.1f}%',
            f'({100*(after_fill-before_fill):+.1f} percentage points)']
original_sha = sha(data_path)
cases = []
for label, misleading in [('actual measured data', False), ('misleading zero-effect contrast first', True)]:
    if misleading:
        real = next(r for r in data['paired_descriptive'] if r['contrast'] == 'LLM minus parser / recovery' and r['scenario'] == 'derived_field_collapse')
        decoy = dict(real, reference_mean_cost=1234.0, treatment_mean_cost=1234.0,
                     reference_mean_fill=0.66, treatment_mean_fill=0.66)
        data['paired_descriptive'] = [decoy, *reversed(data['paired_descriptive'])]
    items = report.make_sections(data, [])[0][1]
    paragraphs = [item for item in items if isinstance(item, str) and item.startswith('For derived-field collapse')]
    assert len(paragraphs) == 1
    paragraph = paragraphs[0]
    assert all(value in paragraph for value in expected), paragraph
    cases.append({'case': label, 'passed': True, 'paragraph': paragraph})
assert sha(data_path) == original_sha
receipt = {'status': 'PASS', 'validated_at_utc': datetime.now(timezone.utc).isoformat(),
           'tests': len(cases), 'cases': cases,
           'expected_cost_before': before_cost, 'expected_cost_after': after_cost,
           'expected_fill_before': before_fill, 'expected_fill_after': after_fill,
           'original_report_data_unchanged': True, 'report_data_sha256': original_sha,
           'report_helper_sha256': sha('/workspace/tools/m5_v2_report.py'),
           'scope': 'Narrative comparison selected from original run means; a preceding ambiguous zero-effect contrast must not replace recovery with a parser comparison. No original artifact changes, model calls or new inventory experiments.'}
(ROOT/'results/v2_report_validation/narrative_regression.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
