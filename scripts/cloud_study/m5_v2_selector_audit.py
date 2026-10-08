"""Score recorded recovery choices against the selector's stated source conditions."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path('/workspace/MasterDissertation/results/v2_pilot')
cases = []
for run in sorted((ROOT/'llm_v2_recovery').glob('B10__*/')):
    for entry in json.loads((run/'trace_index.json').read_text()):
        def read(ref):
            p = run/'artifacts/objects'/f'{ref}.json'
            raw = p.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == ref
            return json.loads(raw)
        trace = read(entry['trace_ref']); refs = trace['references']
        if 'recovery_selection' not in refs:
            continue
        selected = read(refs['recovery_selection'])
        observed = read(refs['observe']); cert = read(refs['observed_certificate'])
        failures = {check['name'] for check in cert['checks'] if check['outcome'] == 'hard_fail'}
        required_checks = {'inventory_distribution_shift', 'stock_movement_balance'} <= failures
        day = observed['lineage']['day']
        current = all(observed['stage_days'].get(k) == day for k in ['inventory', 'sales', 'products'])
        ids = [s['series_id'] for s in observed['series']]
        rows = observed['inventory']
        inventory_ids = [r['series_id'] for r in rows]
        complete = len(set(ids)) == len(ids) == len(rows) == observed['source_row_count'] and set(ids) == set(inventory_ids) and len(set(inventory_ids)) == len(rows)
        ledger = observed['expected_inventory']
        reconciled = set(ledger) == set(ids) and all(
            r.get('source_quantity') is not None and r['unit'] == 'unit'
            and math.isfinite(r['source_quantity']) and r['source_quantity'] >= 0
            and math.isfinite(ledger[r['series_id']]) and ledger[r['series_id']] >= 0
            and abs(r['source_quantity']-ledger[r['series_id']]) <= 1e-8
            for r in rows)
        expected = 'reconcile_current_inventory' if required_checks and current and complete and reconciled else 'hold'
        recovery = trace.get('recovery') or {}
        receipt = read(refs['receipt'])
        cases.append({'run': run.name, 'scenario': run.name.split('__')[1], 'day': day,
                      'trace_ref': entry['trace_ref'], 'observed_ref': refs['observe'],
                      'selection_ref': refs['recovery_selection'],
                      'expected_by_recorded_selector_instruction': expected,
                      'requested_tool': selected['requested_tool'],
                      'instruction_compliant_choice': selected['requested_tool'] == expected,
                      'named_required_anomalies_present': required_checks,
                      'required_source_stages_current': current,
                      'inventory_identity_coverage_complete': complete,
                      'source_ledger_agreement': reconciled,
                      'cited_evidence_refs': selected['evidence_refs'],
                      'tool_status': recovery.get('status'), 'tool_applied': recovery.get('applied'),
                      'receipt_status': receipt['status'],
                      'bad_choice_blocked_before_execution': selected['requested_tool'] != expected and receipt['status'] == 'held' and recovery.get('applied') is False})
assert len(cases) == 20
summary = {'format': 'm5-v2-recovery-selector-instruction-audit-v1',
           'audited_at_utc': datetime.now(timezone.utc).isoformat(),
           'scope': 'Post-decision instruction-compliance assessment of all 20 fresh recovery selections. Labels come only from the observed anomalies/source-stage declarations and source/ledger values. No clean state or future demand is used.',
           'selections': len(cases), 'instruction_compliant': sum(c['instruction_compliant_choice'] for c in cases),
           'incorrect_stale_feed_choices': sum(c['scenario'] == 'feed_gap' and not c['instruction_compliant_choice'] for c in cases),
           'bad_choices_blocked_before_execution': sum(c['bad_choice_blocked_before_execution'] for c in cases),
           'per_scenario': dict(Counter(c['scenario'] for c in cases)),
           'interpretation': 'Zero HTTP/schema errors and exact numeric extraction do not establish correct recovery selection. The small model requested recovery despite stale feeds; independent preconditions and the autonomy gate preserved safety. Prefilter tool availability using deterministic eligibility before asking the model in future versions; this frozen study is not modified.',
           'cases': cases}
(ROOT/'tool_selector_assessment.json').write_text(json.dumps(summary, indent=2))
print(json.dumps({k:v for k,v in summary.items() if k != 'cases'}, indent=2))
