"""Freeze and run a fresh matched architecture comparison; never reuse previous model answers."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from architecture import ARMS, BASE_PATH, OUT, ROOT, LiveClient, base, policy_route, release_permitted, structured_intake
from graph import GRAPH


def now():
    return datetime.now(timezone.utc).isoformat()


def event(stage, **payload):
    OUT.mkdir(parents=True, exist_ok=True)
    row = {'at_utc': now(), 'stage': stage, **payload}
    with (OUT / 'workflow.jsonl').open('a') as stream:
        stream.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


def load(dataset, origin):
    folder = OUT / 'data' / dataset / f'origin_{origin}'
    data = json.loads((folder / 'catalog.json').read_text())
    with np.load(folder / 'panel_and_forecast.npz') as arrays:
        data.update({key: arrays[key] for key in arrays.files})
    return data


def prepare():
    if (OUT / 'data').exists():
        raise FileExistsError('Refuse to overwrite prepared inputs')
    prior = json.loads((base.OUT / 'protocol.json').read_text())
    for dataset, info in prior['datasets'].items():
        for origin in info['origins']:
            old = base.OUT / 'data' / dataset / f'origin_{origin}'
            target = OUT / 'data' / dataset / old.name
            shutil.copytree(old, target)
            for path in old.iterdir():
                if path.is_file():
                    assert base.sha(path) == base.sha(target / path.name)
    base.dump(OUT / 'data/preparation_receipt.json', {
        'status': 'VERIFIED', 'at_utc': now(), 'input_protocol_sha256': base.sha(base.OUT / 'protocol.json'),
        'same_30_series_per_dataset': True, 'same_past_only_forecasts_and_initial_state_rules': True,
        'previous_model_outputs_used': False, 'forecast_retraining': False,
        'note': 'Reuses fixed historical inputs to isolate architectural changes; periods are not unseen research holdouts.'})
    event('inputs_prepared')


def develop():
    folder = OUT / 'development'
    folder.mkdir(exist_ok=False)
    checks = []
    client = LiveClient(folder / 'model_calls')
    for dataset, origin in [('M5', 1927), ('RetailNet', 83)]:
        data = load(dataset, origin)
        for style in range(3):
            terms = base.contracts(data, 'routine', 901, 1)
            message = base.supplier_message(terms, 1, style)
            intake = structured_intake(message)
            answer = intake['extracted'] if intake['route'] == 'structured' else client.ask('supplier', message, f'{dataset}_style{style}')
            exact, slots, failures = base.verify_source(answer, terms)
            checks.append({'dataset': dataset, 'style': style, 'route': intake['route'],
                           'pass': exact, 'correct_slots': slots, 'failures': failures})
    result = {'status': 'PASS' if all(r['pass'] for r in checks) else 'FAIL',
              'at_utc': now(), 'checks': checks, 'fresh_calls': len(client.records),
              'calls': client.records, 'primary_evaluation_outcomes_consulted': False,
              'note': 'Training-derived contract scales and development seed 901; architecture uses unchanged supplier prompts.'}
    base.dump(folder / 'live_smoke_receipt.json', result)
    event('development_complete', status=result['status'], fresh_calls=len(client.records))
    if result['status'] != 'PASS':
        raise RuntimeError('Resolve development failures before freezing')


def freeze():
    if (OUT / 'protocol.json').exists():
        raise FileExistsError('Protocol already frozen')
    smoke = json.loads((OUT / 'development/live_smoke_receipt.json').read_text())
    tests = json.loads((OUT / 'development/numerical_tests.json').read_text())
    assert smoke['status'] == tests['status'] == 'PASS'
    assert json.loads((OUT / 'development/langgraph_integration_receipt.json').read_text())['status'] == 'PASS'
    prior = json.loads((base.OUT / 'protocol.json').read_text())
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10) as stream:
        model = next(m for m in json.load(stream)['models'] if m['name'] == base.MODEL)
    assert model['digest'] == prior['model']['digest']
    started = datetime.now(timezone.utc)
    sources = [BASE_PATH, ROOT / 'scripts/architecture_study/architecture.py', Path(__file__),
               ROOT / 'scripts/architecture_study/graph.py',
               ROOT / 'scripts/architecture_study/analyze.py', ROOT / 'scripts/architecture_study/independent_ledger.py',
               ROOT / 'scripts/architecture_study/requirements.txt',
               ROOT / 'tests/test_selective_architecture.py', ROOT / 'scripts/ollama_clean_study/analyze.py']
    frozen = OUT / 'frozen_code'
    frozen.mkdir(exist_ok=False)
    for path in sources:
        name = 'original_' + path.name if path == BASE_PATH or 'ollama_clean_study' in str(path) else path.name
        shutil.copyfile(path, frozen / name)
    datasets = {}
    for dataset, info in prior['datasets'].items():
        datasets[dataset] = {'series': 30, 'origins': info['origins'], 'days_per_origin': 7,
                             'evaluation_dates': info['evaluation_dates'],
                             'file_sha256': {str(p.relative_to(OUT / 'data' / dataset)): base.sha(p)
                                            for p in (OUT / 'data' / dataset).rglob('*') if p.is_file()}}
    protocol = {
        'schema': 'selective-delegation-architecture-v1', 'status': 'FROZEN', 'frozen_at_utc': started.isoformat(),
        'user_timezone': 'Europe/Paris', 'experiment_cutoff_utc': (started + timedelta(hours=4, minutes=20)).isoformat(),
        'question': 'Does selective delegation improve reliability and computational efficiency while preserving replenishment performance?',
        'arms': {
            'fixed_agents': 'LangGraph fixed path: fresh supplier, coordinator and critic calls on every day; original prompts and model settings',
            'selective_agents': 'LangGraph conditional path: strict table parser or supplier LLM; explicit event-policy router; deterministic release gate; LLM review only when checks fail',
            'structured_planner': 'Same tool and event-policy mapping with authenticated structured supplier fields; no LLM'},
        'datasets': datasets, 'scenarios': base.SCENARIOS, 'simulation_seeds': list(range(201, 231)),
        'days_per_case': 7, 'expected_cases': 360, 'expected_runs': 1080, 'expected_portfolio_days': 7560,
        'expected_fixed_agent_days': 2520, 'expected_selective_agent_days': 2520,
        'expected_fixed_fresh_calls': 7560, 'expected_selective_supplier_calls_if_no_failures': 1680,
        'expected_table_decisions': 840, 'native_llm_response_cache': False, 'llm_retries': 0,
        'failure_policy': 'Hold failed or unknown conditions; record review request; never substitute a comparator action',
        'model': prior['model'], 'simulation': prior['simulation'], 'shared_forecast': prior['shared_forecast'],
        'hypotheses': {
            'A1': 'Selective workflow uses at least 50% fewer native model calls than the fixed workflow',
            'A2': 'Selective workflow has lower mean decision latency in each dataset',
            'A3': 'Selective workflow preserves or improves declared-policy accuracy with no committed-action violations in each dataset',
            'A4': 'Selective workflow preserves performance: lower paired fill bound above -0.10 percentage points and upper paired cost bound below +0.5%',
            'A5_exploratory': 'Any inventory-performance gain is attributable to explicit policy routing rather than a better numerical planner'},
        'success_rule': 'A1-A4 all assessed; do not require or claim service/cost superiority if uncertainty does not establish it',
        'paired_order': 'Alternate fixed/selective execution order with seed+day parity; structured comparator remains common',
        'orchestration': {'framework': 'LangGraph', 'version': version('langgraph'),
                          'langchain_core_version': version('langchain-core'),
                          'compiled_state_graph': True, 'per_decision_node_traces': True,
                          'external_tracing_service': False, 'checkpoint_or_response_cache': False},
        'inference': '30 paired simulation seeds; origins aggregated within seed, scenarios equally weighted; 10,000 bootstrap resamples',
        'prompts': prior['prompts'], 'few_shot_examples': prior['few_shot_examples'],
        'code_sha256': {str(p.relative_to(ROOT)): base.sha(p) for p in sources},
        'baseline_protocol_sha256': base.sha(base.OUT / 'protocol.json'),
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
        'limitations': prior['limitations'] + [
            'Architecture motivated by previously inspected diagnostics; new simulation seeds do not make historical weeks unseen',
            'No measured employee review; malformed-input handling checked separately, not injected into primary sales simulations',
            'One small pretrained model; fewer calls reflect deterministic delegation, not improved model weights',
            'Latency uses the same warmed local server with counterbalanced arm order; token-prefix optimisations may affect timing'],
        'environment': {'os': platform.platform(), 'cpu_quota': Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                        'memory_limit_bytes': int(Path('/sys/fs/cgroup/memory.max').read_text()), 'gpu': False},
    }
    base.dump(OUT / 'protocol.json', protocol)
    event('protocol_frozen', protocol_sha256=base.sha(OUT / 'protocol.json'), expected_runs=1080,
          expected_primary_fresh_calls_without_exceptions=9240)


def verify():
    protocol = json.loads((OUT / 'protocol.json').read_text())
    assert protocol['status'] == 'FROZEN'
    for relative, digest in protocol['code_sha256'].items():
        assert base.sha(ROOT / relative) == digest, relative
    for dataset, info in protocol['datasets'].items():
        for relative, digest in info['file_sha256'].items():
            assert base.sha(OUT / 'data' / dataset / relative) == digest, relative
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10) as stream:
        model = next(m for m in json.load(stream)['models'] if m['name'] == base.MODEL)
    assert model['digest'] == protocol['model']['digest']
    return protocol


def run_case(data, scenario, seed):
    dataset, origin = data['dataset'], data['origin']
    case = f'{dataset}__{scenario}__seed{seed}__origin{origin}'
    folder = OUT / 'runs' / case
    folder.mkdir(parents=True, exist_ok=False)
    clients = {arm: LiveClient(folder / 'model_calls' / arm) for arm in ['fixed_agents', 'selective_agents']}
    inventories = {arm: base.Inventory(data, seed) for arm in ARMS}
    days = {arm: [] for arm in ARMS}
    truth = data['sales'][:, origin:origin+7].copy()
    truth *= base.rng(seed, 'demand', dataset).lognormal(-.005, .1, size=truth.shape)
    if scenario == 'promotion':
        truth[:, 2:] *= 1.3
    base.dump(folder / 'demand_world.json', {'quantities': truth.tolist(), 'seed': seed, 'agents_received_this_file': False})
    with (folder / 'decisions.jsonl').open('w') as stream:
        for day in range(7):
            rules = base.contracts(data, scenario, seed, day)
            message = base.supplier_message(rules, day, (seed + day) % 3)
            business_event = {'active_promotion': scenario == 'promotion' and day >= 2}
            expected = 'service_first' if business_event['active_promotion'] else 'balanced'
            forecast = data['forecast'].copy()
            if business_event['active_promotion']:
                forecast[:, day:] *= 1.3
            order = ['fixed_agents', 'selective_agents'] if (seed + day) % 2 == 0 else ['selective_agents', 'fixed_agents']
            order.append('structured_planner')
            for arm in order:
                env = inventories[arm]
                env.begin(day)
                before_stock = env.stock().copy()
                before_pipeline = [p.copy() for p in env.pending]
                client = clients.get(arm)
                count_before = len(client.records) if client else 0
                start = time.perf_counter()
                decision = GRAPH.invoke({'arm': arm, 'client': client, 'message': message, 'rules': rules,
                                         'event': business_event, 'scenario': scenario, 'day': day, 'env': env,
                                         'forecast': forecast, 'residual_sd': data['residual_sd'], 'groups': data['groups'],
                                         'before_stock': before_stock, 'node_trace': []})
                source_ok, slots, failures = decision['source_ok'], decision['source_slots'], decision['source_failures']
                priority, outputs, delegation = decision['priority'], decision['model_outputs'], decision['delegation']
                target, urgency, proposed = decision['target'], decision['urgency'], decision['proposed']
                solver, action_failures, valid = decision['solver'], decision['action_failures'], decision['valid']
                approved, review_requested = decision['critic_approved'], decision['review_requested']
                permitted, committed = decision['permitted'], decision['committed']
                true_failures = base.checks(committed, rules, data['groups'])
                assert not true_failures, 'Execution gate allowed an invalid order'
                purchase = env.execute(day, committed, rules, data['groups']) if permitted else 0.0
                outcome = env.end(day, truth[:, day])
                calls = client.records[count_before:] if client else []
                row = {'dataset': dataset, 'scenario': scenario, 'seed': seed, 'origin': origin, 'day': day, 'arm': arm,
                       'held': int(not permitted), 'orders': float(committed.sum()), 'purchase_spend': purchase,
                       'actual_violations': len(true_failures), 'source_correct_slots': slots, 'source_exact': int(source_ok),
                       'priority_correct': int(priority == expected), 'critic_should_approve': int(valid), 'critic_approved': int(approved),
                       'critic_false_approval': int(not valid and approved), 'critic_false_hold': int(valid and not approved),
                       'model_calls': len(calls), 'schema_failures': sum(not c['schema_valid'] for c in calls),
                       'input_tokens': sum(c['input_tokens'] for c in calls), 'output_tokens': sum(c['output_tokens'] for c in calls),
                       'agent_seconds': time.perf_counter() - start, 'review_requested': int(review_requested),
                       'structured_intake': int(arm == 'selective_agents' and delegation['route'] == 'structured'),
                       'delegation_route': delegation['route'], 'execution_position': order.index(arm),
                       **{k: v for k, v in outcome.items() if not isinstance(v, list)}}
                days[arm].append(row)
                record = {'row': row, 'stock_before': before_stock.tolist(), 'pending_before': before_pipeline,
                          'batches_after': env.batches, 'source_text': message, 'authoritative_contract': rules,
                          'source_verification_failures': failures, 'chosen_priority': priority, 'expected_priority': expected,
                          'business_event': business_event, 'delegation': delegation, 'model_outputs': outputs,
                          'langgraph_node_trace': decision['node_trace'],
                          'forecast_today': forecast[:, day].tolist(), 'target_gap': target.tolist(), 'urgency': urgency.tolist(),
                          'solver': solver, 'proposed': proposed.tolist(), 'committed': committed.tolist(),
                          'action_checks': action_failures, 'outcome': outcome, 'model_call_records': calls}
                stream.write(json.dumps(record, allow_nan=False) + '\n')
                stream.flush()
            base.dump(OUT / 'progress.json', {'status': 'RUNNING', 'at_utc': now(), 'case': case, 'day_completed': day})
    summaries = []
    for arm in ARMS:
        frame = pd.DataFrame(days[arm])
        frame.to_csv(folder / f'daily_{arm}.csv', index=False)
        env = inventories[arm]
        sold, expired, demand = float(frame.sales.sum()), float(frame.expiry_units.sum()), float(frame.demand.sum())
        pipeline, closing = sum(p['quantity'] for p in env.pending), float(env.stock().sum())
        residual = env.initial_units + float(frame.purchase_spend.sum()) - sold - expired - closing - pipeline
        assert abs(residual) < 1e-5, (case, arm, residual)
        summary = {'dataset': dataset, 'scenario': scenario, 'seed': seed, 'origin': origin, 'arm': arm, 'days': 7,
                   'demand': demand, 'sales': sold, 'fill_rate': sold/demand if demand else 1.0,
                   'operating_cost': float(frame.operating_cost.sum()),
                   'cost_per_demand': float(frame.operating_cost.sum()/demand) if demand else 0.0,
                   'expiry_units': expired, 'expiry_share': expired/(env.initial_units+env.total_receipts),
                   'initial_stock': env.initial_units, 'received_units': env.total_receipts, 'closing_stock': closing,
                   'closing_pipeline': pipeline, 'inventory_balance_residual': residual, 'path': str(folder.relative_to(OUT))}
        for column in ['holding_cost', 'shortage_cost', 'expiry_cost', 'purchase_spend', 'held', 'actual_violations',
                       'source_exact', 'source_correct_slots', 'priority_correct', 'critic_false_approval', 'critic_false_hold',
                       'model_calls', 'schema_failures', 'input_tokens', 'output_tokens', 'agent_seconds',
                       'review_requested', 'structured_intake']:
            summary[column] = float(frame[column].sum())
        summaries.append(summary)
    base.dump(folder / 'summary.json', summaries)
    return summaries


def execute():
    protocol = verify()
    if (OUT / 'execution_receipt.json').exists() or list((OUT / 'runs').glob('*/summary.json')):
        raise FileExistsError('A fresh execution must not overwrite or silently resume previous cases')
    cutoff = datetime.fromisoformat(protocol['experiment_cutoff_utc'])
    datasets = [(dataset, origin, load(dataset, origin)) for dataset, info in protocol['datasets'].items() for origin in info['origins']]
    event('evaluation_started', protocol_sha256=base.sha(OUT / 'protocol.json'))
    summaries, finished_seeds = [], []
    started = time.perf_counter()
    for seed in protocol['simulation_seeds']:
        if datetime.now(timezone.utc) >= cutoff:
            break
        for scenario in protocol['scenarios']:
            for dataset, origin, data in datasets:
                if shutil.disk_usage(ROOT).free < 2 * 1024**3:
                    raise RuntimeError('Disk reserve below 2 GiB')
                event('case_started', dataset=dataset, origin=origin, scenario=scenario, seed=seed, runs_complete=len(summaries))
                case_started = time.perf_counter()
                summaries.extend(run_case(data, scenario, seed))
                pd.DataFrame(summaries).to_csv(OUT / 'summary.csv', index=False)
                calls = int(sum(r['model_calls'] for r in summaries))
                event('case_complete', dataset=dataset, origin=origin, scenario=scenario, seed=seed,
                      seconds=time.perf_counter()-case_started, runs_complete=len(summaries), fresh_calls=calls)
        finished_seeds.append(seed)
        base.dump(OUT / 'seed_progress.json', {'at_utc': now(), 'completed_seeds': finished_seeds,
                                             'runs_complete': len(summaries), 'expected_runs': protocol['expected_runs'],
                                             'elapsed_seconds': time.perf_counter()-started})
    complete = len(summaries) == protocol['expected_runs']
    result = {'status': 'COMPLETE' if complete else 'TIME_LIMIT_PARTIAL', 'at_utc': now(), 'runs': len(summaries),
              'portfolio_days': len(summaries)*7, 'fresh_primary_model_calls': int(sum(r['model_calls'] for r in summaries)),
              'balanced_seeds_complete': finished_seeds, 'elapsed_seconds': time.perf_counter()-started,
              'protocol_sha256': base.sha(OUT / 'protocol.json')}
    base.dump(OUT / 'execution_receipt.json', result)
    event('evaluation_finished', **result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'develop', 'freeze', 'run'])
    getattr(sys.modules[__name__], {'prepare':'prepare', 'develop':'develop', 'freeze':'freeze', 'run':'execute'}[parser.parse_args().phase])()
