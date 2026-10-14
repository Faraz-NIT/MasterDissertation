"""Audit complete recorded LangGraph decisions and estimate every registered architecture measure."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from independent_ledger import keyed_draw, replay_inventory

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'study_results/architecture_study_20261013'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def source_score(extracted, authority):
    rows = extracted.get('rules', []) if isinstance(extracted, dict) else []
    by = {r.get('supplier'): r for r in rows if isinstance(r, dict)}
    correct = int(isinstance(extracted, dict) and extracted.get('budget') == authority['budget'])
    for actual in authority['rules']:
        correct += sum(by.get(actual['supplier'], {}).get(k) == actual[k] for k in ['pack', 'moq', 'lead_days', 'capacity'])
    exact = correct == 13 and len(rows) == 3 and set(by) == {'S1', 'S2', 'S3'}
    return int(exact), int(correct)


def check_quantities(quantities, authority):
    q = np.asarray(quantities)
    failures = []
    if not np.isfinite(q).all() or (q < 0).any():
        failures.append('nonnegative_quantities')
    if q.sum() > authority['budget'] + 1e-7:
        failures.append('budget')
    by = {r['supplier']: r for r in authority['rules']}
    if any(abs(q[i]/by[f'S{i%3+1}']['pack'] - round(q[i]/by[f'S{i%3+1}']['pack'])) > 1e-7 for i in range(30)):
        failures.append('pack_size')
    if any(q[i] > 0 and q[i]+1e-7 < by[f'S{i%3+1}']['moq'] for i in range(30)):
        failures.append('minimum_order')
    for group in range(3):
        if q[np.arange(30)%3 == group].sum() > by[f'S{group+1}']['capacity'] + 1e-7:
            failures.append(f'capacity_S{group+1}')
    return failures


def audit():
    protocol = json.loads((OUT / 'protocol.json').read_text())
    receipt = json.loads((OUT / 'execution_receipt.json').read_text())
    if receipt['status'] != 'COMPLETE':
        raise RuntimeError('Full registered execution must finish before final analysis')
    for name, digest in protocol['code_sha256'].items():
        assert sha(ROOT / name) == digest, f'Frozen code changed: {name}'
    for dataset, info in protocol['datasets'].items():
        for name, digest in info['file_sha256'].items():
            assert sha(OUT / 'data' / dataset / name) == digest, f'Frozen data changed: {name}'
    issues, rows, calls, summaries, timestamps, keys, matching = [], [], [], [], set(), set(), []
    paths = sorted((OUT / 'runs').glob('*/summary.json'))
    for path in paths:
        folder = path.parent
        local_summaries = json.loads(path.read_text())
        summaries.extend(local_summaries)
        records = [json.loads(line) for line in (folder / 'decisions.jsonl').read_text().splitlines()]
        assert len(records) == 21, folder
        issues.extend(replay_inventory(records))
        first = records[0]['row']
        array_path = OUT / f"data/{first['dataset']}/origin_{first['origin']}/panel_and_forecast.npz"
        with np.load(array_path) as array:
            world = array['sales'][:, first['origin']:first['origin']+7].copy()
            forecast = array['forecast'].copy()
        world *= keyed_draw(first['seed'], 'demand', first['dataset']).lognormal(-.005, .1, size=world.shape)
        if first['scenario'] == 'promotion':
            world[:, 2:] *= 1.3
        assert np.allclose(world, json.loads((folder / 'demand_world.json').read_text())['quantities'])
        per_day = {}
        for record in records:
            row = record['row']
            key = tuple(row[k] for k in ['dataset', 'scenario', 'seed', 'origin', 'day', 'arm'])
            assert key not in keys, key
            keys.add(key)
            rows.append(row)
            per_day.setdefault(row['day'], {})[row['arm']] = record
            outcome = record['outcome']
            stock, sold, lost, expired = [np.array(outcome[k]) for k in ['stock_by_series', 'sales_by_series', 'lost_by_series', 'expiry_by_series']]
            assert np.allclose(sold+lost, world[:, row['day']]), key
            assert np.allclose(np.asarray(record['stock_before'])-sold-expired, stock), key
            assert np.isclose(.02*stock.sum()+5*lost.sum()+expired.sum(), row['operating_cost']), key
            assert not check_quantities(record['committed'], record['authoritative_contract']), key
            assert row['actual_violations'] == 0, key
            assert not row['held'] or not np.asarray(record['committed']).any(), key
            assert row['held'] or np.array_equal(record['proposed'], record['committed']), key
            expected_priority = 'service_first' if row['scenario'] == 'promotion' and row['day'] >= 2 else 'balanced'
            assert record['expected_priority'] == expected_priority, key
            assert row['priority_correct'] == int(record['chosen_priority'] == expected_priority), key
            expected_forecast = forecast[:, row['day']].copy()
            if expected_priority == 'service_first':
                expected_forecast *= 1.3
            assert np.allclose(record['forecast_today'], expected_forecast), key
            exact, slots = source_score(record['model_outputs']['supplier'], record['authoritative_contract'])
            assert row['source_exact'] == exact and row['source_correct_slots'] == slots, key
            proposed_failures = check_quantities(record['proposed'], record['authoritative_contract'])
            assert set(proposed_failures) == set(record['action_checks']), key
            if row['arm'] == 'fixed_agents':
                coordination = record['model_outputs']['planner']
                route_ok = bool(coordination and coordination.get('tool') == 'constrained_order')
            else:
                router = record['model_outputs']['policy_router']
                route_ok = bool(router['valid'])
                if route_ok:
                    assert record['chosen_priority'] == expected_priority, key
            valid = bool(exact and route_ok and record['solver']['feasible'] and not proposed_failures and record['delegation']['route'] != 'review')
            assert row['critic_should_approve'] == int(valid), key
            assert row['critic_false_approval'] == int(not valid and row['critic_approved']), key
            assert row['critic_false_hold'] == int(valid and not row['critic_approved']), key
            assert bool(not row['held']) == bool(valid and row['critic_approved']), key
            roles = [r['role'] for r in record['model_call_records']]
            expected_trace = ['supplier_intake']
            if row['arm'] == 'fixed_agents' or record['delegation']['route'] == 'language':
                expected_trace.append('supplier_model')
            expected_trace += ['source_verification', 'llm_coordinator' if row['arm']=='fixed_agents' else 'policy_router',
                               'constrained_planning_tool', 'action_validation']
            if row['arm'] == 'fixed_agents' or row['review_requested']:
                expected_trace.append('llm_review')
            expected_trace.append('release_gate')
            assert record['langgraph_node_trace'] == expected_trace, key
            expected_roles = (['supplier', 'planner', 'critic'] if row['arm'] == 'fixed_agents' else
                              (['supplier'] if record['delegation']['route'] == 'language' else []) +
                              (['critic'] if row['review_requested'] else []))
            assert roles == expected_roles and row['model_calls'] == len(roles), key
            for call in record['model_call_records']:
                file = OUT / call['path']
                assert file.is_relative_to(OUT) and sha(file) == call['sha256'], key
                full = json.loads(file.read_text())
                request, response = full['request'], full.get('response')
                assert request['model'] == protocol['model']['tag'] and request['stream'] is False, key
                assert request['options'] == {'temperature': 0, 'seed': 20261009, 'num_ctx': 4096, 'num_thread': 3, 'num_predict': 512}, key
                assert request['messages'][0] == {'role': 'system', 'content': protocol['prompts'][call['role']]}, key
                assert request['messages'][1:-1] == protocol['few_shot_examples'].get(call['role'], []), key
                assert full['name'] == f"day{row['day']}" and full['role'] == call['role'], key
                assert full['parsed'] == record['model_outputs'][call['role']], key
                if call['role'] == 'supplier':
                    assert request['messages'][-1]['content'] == record['source_text'], key
                if response:
                    assert response['model'] == protocol['model']['tag'], key
                    assert response['created_at'] not in timestamps, key
                    timestamps.add(response['created_at'])
                    assert call['input_tokens'] == response.get('prompt_eval_count', 0), key
                    assert call['output_tokens'] == response.get('eval_count', 0), key
                    if full['schema_valid']:
                        assert full['parsed'] == json.loads(response['message']['content']), key
                calls.append({**{k: row[k] for k in ['dataset', 'scenario', 'seed', 'origin', 'day', 'arm']}, **call})
        for day, arms in per_day.items():
            assert set(arms) == set(protocol['arms']), folder
            selective, reference = arms['selective_agents'], arms['structured_planner']
            matching.append({**{k: selective['row'][k] for k in ['dataset', 'scenario', 'seed', 'origin', 'day']},
                             'orders_identical_to_structured': np.array_equal(selective['committed'], reference['committed'])})
        for summary in local_summaries:
            frame = pd.DataFrame([r['row'] for r in records if r['row']['arm'] == summary['arm']])
            for name in ['demand', 'sales', 'operating_cost', 'purchase_spend', 'expiry_units', 'model_calls', 'agent_seconds']:
                assert np.isclose(frame[name].sum(), summary[name]), (folder, name)
            assert np.isclose(frame.sales.sum()/frame.demand.sum(), summary['fill_rate']), folder
            balance = summary['initial_stock']+summary['purchase_spend']-summary['sales']-summary['expiry_units']-summary['closing_stock']-summary['closing_pipeline']
            assert abs(balance) < 1e-5, folder
    assert not issues, issues[:10]
    expected_keys = {(dataset, scenario, seed, origin, day, arm)
                     for dataset, info in protocol['datasets'].items() for origin in info['origins']
                     for scenario in protocol['scenarios'] for seed in protocol['simulation_seeds']
                     for day in range(7) for arm in protocol['arms']}
    assert keys == expected_keys, 'Registered decision grid differs'
    runs, days, model = pd.DataFrame(summaries), pd.DataFrame(rows), pd.DataFrame(calls)
    master = pd.read_csv(OUT / 'summary.csv')
    sort = ['dataset', 'scenario', 'seed', 'origin', 'arm']
    left, right = runs.sort_values(sort).reset_index(drop=True), master.sort_values(sort).reset_index(drop=True)
    assert left[sort].equals(right[sort])
    for column in runs.select_dtypes(include='number').columns:
        assert np.allclose(left[column], right[column]), column
    assert len(runs) == protocol['expected_runs'] and len(days) == protocol['expected_portfolio_days']
    assert int((model.arm == 'fixed_agents').sum()) == protocol['expected_fixed_fresh_calls']
    assert len(calls) == receipt['fresh_primary_model_calls']
    output = OUT / 'analysis'
    output.mkdir(exist_ok=True)
    runs.to_csv(output / 'run_results.csv', index=False)
    days.to_csv(output / 'daily_results.csv', index=False)
    model.to_csv(output / 'model_calls.csv', index=False)
    pd.DataFrame(matching).to_csv(output / 'matched_actions.csv', index=False)
    dump(output / 'audit_receipt.json', {
        'status': 'VERIFIED', 'at_utc': datetime.now(timezone.utc).isoformat(),
        'runs': len(runs), 'portfolio_days': len(days), 'series_days': len(days)*30,
        'fresh_primary_model_calls': len(calls), 'unique_native_response_timestamps': len(timestamps),
        'native_calls_without_returned_response': len(calls)-len(timestamps), 'issues': [],
        'checks': ['Frozen code and data hashes', 'Complete registered matched grid', 'Independent FIFO and supplier-ledger replay',
                   'Matched demand and forecasts', 'Recomputed inventory costs', 'Pack/MOQ/budget/capacity checks',
                   'Source accuracy and declared-priority scores', 'Every LangGraph path and role-call count',
                   'Every native model request/response hash and generation configuration', 'Unique native response timestamps',
                   'Held actions never released', 'Master summary agrees with per-case records'],
        'protocol_sha256': sha(OUT / 'protocol.json')})
    return runs, days, model


def estimate(values):
    values = np.asarray(values, dtype=float)
    generator = np.random.default_rng(20261014)
    resamples = values[generator.integers(0, len(values), size=(10000, len(values)))].mean(axis=1)
    return {'mean': float(values.mean()), 'ci_low': float(np.quantile(resamples, .025)),
            'ci_high': float(np.quantile(resamples, .975)), 'simulation_seeds': len(values)}


def analyze(runs, days, model):
    sums = ['demand', 'sales', 'operating_cost', 'expiry_units', 'initial_stock', 'received_units', 'days',
            'model_calls', 'agent_seconds', 'priority_correct', 'source_exact', 'source_correct_slots',
            'actual_violations', 'held', 'review_requested', 'structured_intake', 'input_tokens', 'output_tokens']
    seeds = runs.groupby(['dataset', 'scenario', 'arm', 'seed'])[sums].sum().reset_index()
    seeds['fill_rate'] = seeds.sales/seeds.demand
    seeds['cost_per_demand'] = seeds.operating_cost/seeds.demand
    seeds['expiry_share'] = seeds.expiry_units/(seeds.initial_stock+seeds.received_units)
    seeds['mean_decision_seconds'] = seeds.agent_seconds/seeds.days
    seeds['calls_per_day'] = seeds.model_calls/seeds.days
    seeds['priority_accuracy'] = seeds.priority_correct/seeds.days
    metric_columns = ['fill_rate', 'cost_per_demand', 'expiry_share', 'mean_decision_seconds', 'calls_per_day', 'priority_accuracy']
    overall = seeds.groupby(['dataset', 'arm', 'seed'])[metric_columns].mean().reset_index()
    means, effects = [], []
    for (dataset, scenario, arm), group in seeds.groupby(['dataset', 'scenario', 'arm']):
        means.append({'dataset': dataset, 'scenario': scenario, 'arm': arm,
                      **{metric: estimate(group[metric]) for metric in metric_columns}})
    for scenario, values in [('overall', overall), *[(s, seeds[seeds.scenario == s]) for s in sorted(seeds.scenario.unique())]]:
        for dataset, group in values.groupby('dataset'):
            selective = group[group.arm == 'selective_agents'].set_index('seed').sort_index()
            for comparator in ['fixed_agents', 'structured_planner']:
                reference = group[group.arm == comparator].set_index('seed').sort_index()
                for metric, unit, scale, relative in [
                    ('fill_rate', 'percentage_points', 100, False), ('cost_per_demand', 'relative_percent', 100, True),
                    ('expiry_share', 'percentage_points', 100, False), ('mean_decision_seconds', 'seconds', 1, False),
                    ('calls_per_day', 'calls_per_day', 1, False), ('priority_accuracy', 'percentage_points', 100, False)]:
                    difference = (selective[metric]/reference[metric]-1)*scale if relative else (selective[metric]-reference[metric])*scale
                    effects.append({'dataset': dataset, 'scenario': scenario, 'comparison': comparator,
                                    'metric': metric, 'unit': unit, **estimate(difference)})
    diagnostics = []
    for (dataset, arm), group in days.groupby(['dataset', 'arm']):
        active = group[(group.scenario == 'promotion') & (group.day >= 2)]
        diagnostics.append({'dataset': dataset, 'arm': arm, 'portfolio_days': len(group),
                            'fresh_model_calls': int(group.model_calls.sum()), 'structured_table_decisions': int(group.structured_intake.sum()),
                            'exact_source_accuracy': float(group.source_exact.mean()), 'priority_accuracy': float(group.priority_correct.mean()),
                            'active_promotion_accuracy': float(active.priority_correct.mean()),
                            'priority_errors': int((1-group.priority_correct).sum()), 'mean_decision_seconds': float(group.agent_seconds.mean()),
                            'p95_decision_seconds': float(group.agent_seconds.quantile(.95)), 'held_days': int(group.held.sum()),
                            'review_requests': int(group.review_requested.sum()), 'committed_violations': int(group.actual_violations.sum()),
                            'input_tokens': int(group.input_tokens.sum()), 'output_tokens': int(group.output_tokens.sum())})
    verdicts = []
    for dataset in sorted(days.dataset.unique()):
        selected = {e['metric']: e for e in effects if e['dataset'] == dataset and e['scenario'] == 'overall' and e['comparison'] == 'fixed_agents'}
        ds = {r['arm']: r for r in diagnostics if r['dataset'] == dataset}
        reduction = 100*(1-ds['selective_agents']['fresh_model_calls']/ds['fixed_agents']['fresh_model_calls'])
        verdicts.append({'dataset': dataset, 'A1_call_reduction_pct': reduction, 'A1_supported': reduction >= 50,
                         'A2_supported': selected['mean_decision_seconds']['ci_high'] < 0,
                         'A3_supported': ds['selective_agents']['priority_errors'] <= ds['fixed_agents']['priority_errors'] and ds['selective_agents']['committed_violations'] == 0,
                         'A4_supported': selected['fill_rate']['ci_low'] > -.10 and selected['cost_per_demand']['ci_high'] < .5,
                         'service_superiority_supported': selected['fill_rate']['ci_low'] > 0,
                         'cost_superiority_supported': selected['cost_per_demand']['ci_high'] < 0})
    output = OUT / 'analysis'
    seeds.to_csv(output / 'seed_results.csv', index=False)
    overall.to_csv(output / 'overall_seed_results.csv', index=False)
    pd.DataFrame(effects).to_csv(output / 'paired_effects.csv', index=False)
    pd.DataFrame(diagnostics).to_csv(output / 'diagnostics.csv', index=False)
    dump(output / 'analysis_summary.json', {'status': 'COMPLETE', 'policy_means': means, 'paired_effects': effects,
        'diagnostics': diagnostics, 'registered_assessments': verdicts,
        'all_registered_success_conditions_met': all(all(r[k] for k in ['A1_supported','A2_supported','A3_supported','A4_supported']) for r in verdicts),
        'inference_note': 'Conditional simulated-seed uncertainty; historical weeks previously studied. Neither retailer-population inference nor independent model replications.',
        'attribution_note': 'Same forecast and numerical planner across arms. Routing, structured parsing and omitted routine LLM calls are architectural changes, not model training.'})
    print(json.dumps({'audit': 'VERIFIED', 'runs': len(runs), 'fresh_calls': len(model), 'assessments': verdicts}, indent=2))


if __name__ == '__main__':
    analyze(*audit())
