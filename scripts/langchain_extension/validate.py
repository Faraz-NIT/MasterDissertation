"""Audit fresh LangChain records without presenting one-seed intervals as evidence."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parent))
from chain import ROOT,base
from validation_run import OUT,now
sys.path.insert(0,str(ROOT/'scripts/architecture_study'))
import analyze as previous_audit
import independent_ledger


def audit():
    protocol = json.loads((OUT/'protocol.json').read_text())
    receipt = json.loads((OUT/'execution_receipt.json').read_text())
    assert receipt['status'] == 'COMPLETE'
    for name,digest in protocol['code_sha256'].items():
        assert base.sha(ROOT/name) == digest
    for dataset,info in protocol['datasets'].items():
        for name,digest in info['file_sha256'].items():
            assert base.sha(OUT/'data'/dataset/name) == digest
    independent_ledger.OUT = OUT
    keys,timestamps = set(),set()
    rows,calls,runs,matches = [],[],[],[]
    for path in sorted((OUT/'runs').glob('*/summary.json')):
        folder = path.parent
        local = json.loads(path.read_text())
        records = [json.loads(line) for line in (folder/'decisions.jsonl').read_text().splitlines()]
        assert len(records) == 21 and not independent_ledger.replay_inventory(records)
        first = records[0]['row']
        with np.load(OUT/f"data/{first['dataset']}/origin_{first['origin']}/panel_and_forecast.npz") as arrays:
            world = arrays['sales'][:,first['origin']:first['origin']+7].copy()
            forecast = arrays['forecast'].copy()
        world *= independent_ledger.keyed_draw(first['seed'],'demand',first['dataset']).lognormal(-.005,.1,size=world.shape)
        if first['scenario'] == 'promotion': world[:,2:] *= 1.3
        assert np.allclose(world,json.loads((folder/'demand_world.json').read_text())['quantities'])
        by_day = {}
        for record in records:
            row = record['row']; rows.append(row)
            key = tuple(row[k] for k in ['dataset','scenario','seed','origin','day','arm'])
            assert key not in keys; keys.add(key)
            by_day.setdefault(row['day'],{})[row['arm']] = record
            assert record['orchestration_framework'] == 'LangChain LCEL'
            assert 'langgraph_node_trace' not in record
            expected = 'service_first' if row['scenario'] == 'promotion' and row['day'] >= 2 else 'balanced'
            assert record['expected_priority'] == expected
            assert row['priority_correct'] == int(record['chosen_priority'] == expected)
            correct,slots = previous_audit.source_score(record['model_outputs']['supplier'],record['authoritative_contract'])
            assert row['source_exact'] == correct and row['source_correct_slots'] == slots
            action_failures = previous_audit.check_quantities(record['proposed'],record['authoritative_contract'])
            assert set(record['action_checks']) == set(action_failures)
            assert not previous_audit.check_quantities(record['committed'],record['authoritative_contract'])
            assert row['actual_violations'] == 0
            assert not row['held'] or not np.asarray(record['committed']).any()
            routing = record['model_outputs']['planner'] if row['arm'] == 'fixed_agents' else record['model_outputs']['policy_router']
            route_ok = bool(routing and (routing.get('tool') == 'constrained_order' if row['arm'] == 'fixed_agents' else routing['valid']))
            valid = bool(correct and route_ok and record['solver']['feasible'] and not action_failures and record['delegation']['route'] != 'review')
            assert row['critic_should_approve'] == int(valid)
            assert row['held'] == int(not (valid and row['critic_approved']))
            if not row['held']: assert np.array_equal(record['proposed'],record['committed'])
            trace = ['supplier_intake']
            extraction = row['arm'] == 'fixed_agents' or record['delegation']['route'] == 'language'
            if extraction: trace += ['supplier_model']
            trace += ['source_verification','llm_coordinator' if row['arm'] == 'fixed_agents' else 'policy_router',
                      'constrained_planning_tool','action_validation']
            review = row['arm'] == 'fixed_agents' or row['review_requested']
            if review: trace += ['llm_review']
            trace += ['release_gate']
            assert record['langchain_step_trace'] == trace
            expected_roles = (['supplier','planner','critic'] if row['arm'] == 'fixed_agents' else
                              (['supplier'] if extraction else [])+(['critic'] if review else []))
            assert [call['role'] for call in record['model_call_records']] == expected_roles
            assert row['model_calls'] == len(expected_roles)
            for call in record['model_call_records']:
                file = OUT/call['path']
                assert file.is_relative_to(OUT) and base.sha(file) == call['sha256']
                full = json.loads(file.read_text()); request = full['request']; response = full.get('response')
                assert request['model'] == protocol['model']['tag'] and request['stream'] is False
                assert request['options'] == {'temperature':0,'seed':20261009,'num_ctx':4096,'num_thread':3,'num_predict':512}
                assert request['messages'][0] == {'role':'system','content':protocol['prompts'][call['role']]}
                assert request['messages'][1:-1] == protocol['few_shot_examples'].get(call['role'],[])
                assert full['parsed'] == record['model_outputs'][call['role']]
                assert call['schema_valid'] == full['schema_valid']
                if call['role'] == 'supplier': assert request['messages'][-1]['content'] == record['source_text']
                assert response and response['created_at'] not in timestamps
                assert response['model'] == protocol['model']['tag']; timestamps.add(response['created_at'])
                if call['schema_valid']: assert full['parsed'] == json.loads(response['message']['content'])
                assert call['input_tokens'] == response.get('prompt_eval_count',0)
                assert call['output_tokens'] == response.get('eval_count',0)
                calls.append({**{k:row[k] for k in ['dataset','scenario','seed','origin','day','arm']},**call})
            outcome = record['outcome']
            stock,sold,lost,expired = [np.asarray(outcome[k]) for k in
                                      ['stock_by_series','sales_by_series','lost_by_series','expiry_by_series']]
            assert np.allclose(sold+lost,world[:,row['day']])
            assert np.allclose(np.asarray(record['stock_before'])-sold-expired,stock)
            assert np.isclose(.02*stock.sum()+5*lost.sum()+expired.sum(),row['operating_cost'])
            expected_forecast = forecast[:,row['day']]*(1.3 if expected == 'service_first' else 1.)
            assert np.allclose(record['forecast_today'],expected_forecast)
        for day,arms in by_day.items():
            assert set(arms) == set(protocol['arms'])
            matches.append({'dataset':first['dataset'],'origin':first['origin'],'scenario':first['scenario'],'day':day,
                            'orders_identical_to_structured':np.array_equal(arms['selective_agents']['committed'],arms['structured_planner']['committed'])})
        for summary in local:
            frame = pd.DataFrame([r['row'] for r in records if r['row']['arm'] == summary['arm']])
            for name in ['demand','sales','operating_cost','purchase_spend','expiry_units','model_calls','agent_seconds']:
                assert np.isclose(frame[name].sum(),summary[name])
            balance = summary['initial_stock']+summary['purchase_spend']-summary['sales']-summary['expiry_units']-summary['closing_stock']-summary['closing_pipeline']
            assert abs(balance) < 1e-5
        runs.extend(local)
    expected = {(dataset,scenario,seed,origin,day,arm)
                for dataset,info in protocol['datasets'].items() for origin in info['origins']
                for scenario in protocol['scenarios'] for seed in protocol['simulation_seeds']
                for day in range(7) for arm in protocol['arms']}
    assert keys == expected and len(runs) == 36 and len(rows) == 252
    assert len(calls) == receipt['fresh_primary_model_calls']
    output = OUT/'analysis'; output.mkdir(exist_ok=True)
    days,run_frame,call_frame = pd.DataFrame(rows),pd.DataFrame(runs),pd.DataFrame(calls)
    master = pd.read_csv(OUT/'summary.csv'); order = ['dataset','scenario','seed','origin','arm']
    left,right = run_frame.sort_values(order).reset_index(drop=True),master.sort_values(order).reset_index(drop=True)
    assert left[order].equals(right[order])
    for column in run_frame.select_dtypes(include='number'): assert np.allclose(left[column],right[column])
    assert int(call_frame.arm.eq('fixed_agents').sum()) == protocol['expected_fixed_fresh_calls']
    for name,frame in [('daily_results',days),('run_results',run_frame),('model_calls',call_frame),('matched_actions',pd.DataFrame(matches))]:
        frame.to_csv(output/f'{name}.csv',index=False)
    diagnostics = []
    scenario = run_frame.groupby(['dataset','arm','scenario'])[['sales','demand','operating_cost']].sum()
    scenario['fill_rate'] = scenario.sales/scenario.demand
    scenario['cost_per_demand'] = scenario.operating_cost/scenario.demand
    means = scenario.groupby(['dataset','arm'])[['fill_rate','cost_per_demand']].mean()
    for (dataset,arm),group in days.groupby(['dataset','arm']):
        diagnostics.append({'dataset':dataset,'arm':arm,'portfolio_days':len(group),
                            'fresh_model_calls':int(group.model_calls.sum()),'priority_accuracy':float(group.priority_correct.mean()),
                            'source_accuracy':float(group.source_exact.mean()),'mean_decision_seconds':float(group.agent_seconds.mean()),
                            'held':int(group.held.sum()),'violations':int(group.actual_violations.sum()),
                            'fill_rate':float(means.loc[(dataset,arm),'fill_rate']),
                            'cost_per_demand':float(means.loc[(dataset,arm),'cost_per_demand'])})
    audit = {'status':'VERIFIED','at_utc':now(),'runs':len(runs),'portfolio_days':len(rows),'series_days':len(rows)*30,
             'fresh_model_calls':len(calls),'unique_native_timestamps':len(timestamps),'issues':[],
             'checks':['Frozen code/data hashes','Complete matched grid','Independent FIFO ledger',
                       'Source and priority accuracy','Held actions not released','Every LangChain step and model-role path',
                       'Fresh native request/response hashes and model settings','Recomputed cost and quantities','Master summary agreement'],
             'inferential_analysis':False,'protocol_sha256':base.sha(OUT/'protocol.json')}
    base.dump(output/'audit_receipt.json',audit)
    summary = {'scope':'Fresh one-seed LangChain implementation validation','simulation_seeds':[233],
               'diagnostics':diagnostics,'selective_orders_identical_to_structured':bool(pd.DataFrame(matches).orders_identical_to_structured.all()),
               'confidence_intervals':None,'explanation':'One seed validates execution; it does not replace the completed 30-seed architecture study.'}
    base.dump(output/'validation_summary.json',summary)
    print(json.dumps(audit))


if __name__ == '__main__':
    audit()
