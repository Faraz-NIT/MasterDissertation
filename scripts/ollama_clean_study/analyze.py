"""Audit recorded decisions independently and produce seed-level comparisons."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'study_results/ollama_clean_study_20261009'


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def dump(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def keyed_draw(seed,*parts):
    key=json.dumps([int(seed),*parts],separators=(',',':'))
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big'))


def replay_inventory(records):
    """Rebuild the physical ledger without importing the evaluated simulator."""
    first=records[0]['row'];dataset=first['dataset'];origin=first['origin']
    with np.load(OUT/f'data/{dataset}/origin_{origin}/panel_and_forecast.npz') as arrays:
        opening=np.ceil(arrays['historical_mean']*3)
    shelf=3 if dataset=='RetailNet' else 10000
    states={};issues=[]
    for arm in ('conventional','structured_planner','llm_agents'):
        batches=[]
        for quantity in opening:
            if shelf==3:
                base,remainder=divmod(int(quantity),3)
                batches.append([[float(base+int(j>=3-remainder)),j] for j in range(3) if base+int(j>=3-remainder)])
            else:batches.append([[float(quantity),shelf]] if quantity else [])
        states[arm]={'batches':batches,'pending':[],'day':0}
    for record in records:
        row=record['row'];day=row['day'];state=states[row['arm']]
        key=f"{dataset}/{origin}/{row['scenario']}/{row['seed']}/{row['arm']}/{day}"
        if state['day']!=day:issues.append('Replay day sequence '+key)
        state['day']+=1;received=0.;remaining=[]
        for delivery in state['pending']:
            if delivery['due']<=day:
                state['batches'][delivery['series']].append([delivery['quantity'],day+shelf-1])
                received+=delivery['quantity']
            else:remaining.append(delivery)
        state['pending']=remaining
        if state['pending']!=record['pending_before']:issues.append('Replay pending supply '+key)
        before=np.array([sum(q for q,_ in batches) for batches in state['batches']])
        if not np.allclose(before,record['stock_before'],atol=1e-7):issues.append('Replay opening stock '+key)
        purchase=0.;rules={r['supplier']:r for r in record['authoritative_contract']['rules']}
        for series,quantity in enumerate(record['committed']):
            if not quantity:continue
            draw=keyed_draw(row['seed'],'supply',day,series)
            cancelled=draw.random()<.02;fraction=draw.choice([.8,1.],p=[.1,.9])
            amount=0. if cancelled else float(np.floor(quantity*fraction))
            delay=int(draw.choice([0,1],p=[.9,.1]))
            if amount:
                state['pending'].append({'series':series,'quantity':amount,'due':day+rules[f'S{series%3+1}']['lead_days']+delay,'ordered':day})
                purchase+=amount
        demand=np.asarray(record['outcome']['demand_by_series']);sales=np.minimum(before,demand)
        expired=np.zeros(30)
        for series,batches in enumerate(state['batches']):
            consume=sales[series];kept=[]
            for quantity,expiry in sorted(batches,key=lambda batch:batch[1]):
                used=min(quantity,consume);quantity-=used;consume-=used
                if expiry<=day:expired[series]+=quantity
                elif quantity>1e-9:kept.append([quantity,expiry])
            state['batches'][series]=kept
        for field,value in [('sales_by_series',sales),('expiry_by_series',expired)]:
            if not np.allclose(record['outcome'][field],value,atol=1e-7):issues.append('Replay '+field+' '+key)
        for batches,logged in zip(state['batches'],record['batches_after']):
            if len(batches)!=len(logged) or (batches and not np.allclose(batches,logged,atol=1e-7)):
                issues.append('Replay FIFO batches '+key);break
        if not np.isclose(received,row['received_units'],atol=1e-7):issues.append('Replay received units '+key)
        if not np.isclose(purchase,row['purchase_spend'],atol=1e-7):issues.append('Replay fulfilled-purchase spend '+key)
    return issues


def audit(allow_partial=False):
    p=json.loads((OUT/'protocol.json').read_text())
    receipt=json.loads((OUT/'execution_receipt.json').read_text())
    if receipt['status']!='COMPLETE' and not allow_partial:
        raise RuntimeError('Evaluation must finish before final analysis')
    issues=[];daily=[];calls=[];summaries=[];styles=[];matches=[];created=set();decision_keys=set()
    for rel,expected in p['code_sha256'].items():
        if sha(ROOT/rel)!=expected:issues.append('Frozen source changed: '+rel)
    for dataset,info in p['datasets'].items():
        for rel,expected in info['file_sha256'].items():
            if sha(OUT/'data'/dataset/rel)!=expected:issues.append('Frozen data changed: '+dataset+'/'+rel)
    paths=sorted((OUT/'runs').glob('*/summary.json'))
    for path in paths:
        root=path.parent
        local_summaries=json.loads(path.read_text());summaries.extend(local_summaries)
        records=[json.loads(line) for line in (root/'decisions.jsonl').read_text().splitlines()]
        if len(records)!=21:issues.append('Wrong decision count: '+str(root))
        issues.extend(replay_inventory(records))
        world=json.loads((root/'demand_world.json').read_text())['quantities']
        first=records[0]['row']
        with np.load(OUT/f"data/{first['dataset']}/origin_{first['origin']}/panel_and_forecast.npz") as arrays:
            declared_world=arrays['sales'][:,first['origin']:first['origin']+7].copy()
        declared_world*=keyed_draw(first['seed'],'demand',first['dataset']).lognormal(-.5*.1**2,.1,size=declared_world.shape)
        if first['scenario']=='promotion':declared_world[:,2:]*=1.3
        if not np.allclose(world,declared_world,atol=1e-7):issues.append('Declared demand generation differs: '+str(root))
        perday={}
        for record in records:
            row=record['row'];arm=row['arm'];n=row['day'];groups=np.arange(30)%3
            key=tuple(row[k] for k in ('dataset','scenario','seed','origin','day','arm'))
            if key in decision_keys:issues.append('Duplicate decision '+str(key))
            decision_keys.add(key)
            daily.append(row)
            outcome=record['outcome'];expected_demand=np.array(world)[:,n]
            sold=np.array(outcome['sales_by_series']);lost=np.array(outcome['lost_by_series'])
            expired=np.array(outcome['expiry_by_series']);stock=np.array(outcome['stock_by_series'])
            before=np.array(record['stock_before'])
            if not np.allclose(np.array(outcome['demand_by_series']),expected_demand,atol=1e-7):issues.append('Unmatched demand '+str(key))
            if not np.allclose(sold+lost,expected_demand,atol=1e-7):issues.append('Demand balance '+str(key))
            if not np.allclose(before-sold-expired,stock,atol=1e-7):issues.append('Stock balance '+str(key))
            if (sold<0).any() or (stock<-1e-7).any() or (lost<-1e-7).any():issues.append('Negative physical state '+str(key))
            if not np.allclose([sum(q for q,_ in batch) for batch in record['batches_after']],stock,atol=1e-7):issues.append('Age-batch balance '+str(key))
            cost=float(.02*stock.sum()+5*lost.sum()+expired.sum())
            if not np.isclose(cost,row['operating_cost'],atol=1e-6):issues.append('Cost decomposition '+str(key))
            for field,value in [('sales',sold.sum()),('lost',lost.sum()),('demand',expected_demand.sum()),
                ('stock',stock.sum()),('expiry_units',expired.sum()),('holding_cost',.02*stock.sum()),
                ('shortage_cost',5*lost.sum()),('expiry_cost',expired.sum())]:
                if not np.isclose(row[field],value,atol=1e-7):issues.append('Daily aggregate differs: '+field+' '+str(key))
            q=np.asarray(record['committed']);proposed=np.asarray(record['proposed'])
            if row['held'] and q.any():issues.append('Held order executed '+str(key))
            if not row['held'] and not np.array_equal(q,proposed):issues.append('Executed order differs '+str(key))
            rules=record['authoritative_contract'];by={r['supplier']:r for r in rules['rules']}
            failures=[]
            if not np.isfinite(q).all() or (q<0).any():failures.append('nonnegative')
            if q.sum()>rules['budget']+1e-7:failures.append('budget')
            for i,amount in enumerate(q):
                rule=by[f'S{groups[i]+1}']
                if abs(amount/rule['pack']-round(amount/rule['pack']))>1e-7:failures.append('pack')
                if amount>0 and amount+1e-7<rule['moq']:failures.append('moq')
            for g in range(3):
                if q[groups==g].sum()>by[f'S{g+1}']['capacity']+1e-7:failures.append('capacity')
            if failures:issues.append('Committed constraint violation '+str(key)+str(failures))
            if int(row['actual_violations'])!=len(failures):issues.append('Incorrect violation count '+str(key))
            perday.setdefault(n,{})[arm]=record
            if arm=='llm_agents':
                referenced=record['model_call_records']
                if len(referenced)!=3 or {r['role'] for r in referenced}!={'supplier','planner','critic'}:issues.append('Not three agent calls '+str(key))
                extracted=record['model_outputs']['supplier']
                extracted_rows={r['supplier']:r for r in extracted['rules']} if extracted else {}
                correct=int(bool(extracted and extracted.get('budget')==rules['budget']))
                exact=bool(extracted and extracted.get('budget')==rules['budget'] and len(extracted['rules'])==3 and set(extracted_rows)==set(by))
                for sup,true in by.items():
                    for field in ('pack','moq','lead_days','capacity'):
                        ok=extracted_rows.get(sup,{}).get(field)==true[field]
                        correct+=int(ok);exact=exact and ok
                if correct!=row['source_correct_slots'] or int(exact)!=row['source_exact']:issues.append('Source accuracy count '+str(key))
                routing=record['model_outputs']['planner']
                route_valid=bool(routing and routing.get('tool')=='constrained_order')
                reviewer=record['model_outputs']['critic']
                approved=bool(reviewer and reviewer.get('verdict')=='approve')
                expected_priority='service_first' if row['scenario']=='promotion' and n>=2 else 'balanced'
                if record['expected_priority']!=expected_priority:issues.append('Expected priority differs '+str(key))
                if row['priority_correct']!=int(record['chosen_priority']==expected_priority):issues.append('Priority score differs '+str(key))
                independent_valid=bool(exact and route_valid and record['solver']['feasible'] and not record['action_checks'])
                if row['critic_should_approve']!=int(independent_valid):issues.append('Review ground truth differs '+str(key))
                if row['critic_false_approval']!=int(not independent_valid and approved):issues.append('False-approval score differs '+str(key))
                if row['critic_false_hold']!=int(independent_valid and not approved):issues.append('False-hold score differs '+str(key))
                if not row['held'] and not (exact and route_valid and approved and record['solver']['feasible']):
                    issues.append('Execution occurred without all gate conditions '+str(key))
                styles.append({'dataset':row['dataset'],'scenario':row['scenario'],'seed':row['seed'],'origin':row['origin'],'day':n,'style':(row['seed']+n)%3,'exact':int(exact),'correct_slots':correct})
                for call in referenced:
                    source=OUT/call['path']
                    if sha(source)!=call['sha256']:issues.append('Call hash mismatch '+str(source))
                    full=json.loads(source.read_text());request=full['request'];response=full.get('response')
                    if full['role']!=call['role'] or full['name']!=f'day{n}':issues.append('Role/day call identity differs '+str(source))
                    if full['schema_valid']!=call['schema_valid'] or full['seconds']!=call['seconds']:issues.append('Call metadata differs '+str(source))
                    if request['messages'][0]!={'role':'system','content':p['prompts'][call['role']]}:issues.append('Frozen prompt changed '+str(source))
                    examples=p['few_shot_examples'].get(call['role'],[])
                    if request['messages'][1:-1]!=examples:issues.append('Frozen examples changed '+str(source))
                    if record['model_outputs'][call['role']]!=full['parsed']:issues.append('Decision used different model output '+str(source))
                    if request['model']!=p['model']['tag'] or request['stream'] is not False:issues.append('Unexpected call model or route '+str(source))
                    if request['options']!={"temperature":0,"seed":20261009,"num_ctx":4096,"num_thread":3,"num_predict":512}:issues.append('Generation settings changed '+str(source))
                    if response:
                        timestamp=response.get('created_at')
                        if timestamp in created:issues.append('Duplicated model response timestamp '+str(source))
                        created.add(timestamp)
                        if response.get('model')!=p['model']['tag']:issues.append('Response model changed '+str(source))
                        if response.get('prompt_eval_count',0)!=call['input_tokens'] or response.get('eval_count',0)!=call['output_tokens']:issues.append('Token score differs '+str(source))
                        if full['schema_valid'] and json.loads(response['message']['content'])!=full['parsed']:issues.append('Parsed response changed '+str(source))
                    calls.append({**{k:row[k] for k in ('dataset','scenario','seed','origin','day')},**call})
        for n,arms in perday.items():
            if set(arms)!={'conventional','structured_planner','llm_agents'}:issues.append('Missing matched arm '+str(root))
            if len(arms)==3:
                left=arms['llm_agents'];right=arms['structured_planner']
                matches.append({**{k:left['row'][k] for k in ('dataset','scenario','seed','origin','day')},
                    'orders_identical':np.array_equal(left['committed'],right['committed']),
                    'hold_identical':left['row']['held']==right['row']['held']})
        for summary in local_summaries:
            frame=pd.DataFrame([r['row'] for r in records if r['row']['arm']==summary['arm']])
            for column,target in [('operating_cost','operating_cost'),('sales','sales'),('demand','demand'),('purchase_spend','purchase_spend'),('expiry_units','expiry_units')]:
                if not np.isclose(frame[column].sum(),summary[target],atol=1e-6):issues.append('Summary sum differs '+str(root)+' '+target)
            if not np.isclose(frame.sales.sum()/frame.demand.sum(),summary['fill_rate'],atol=1e-10):issues.append('Fill ratio differs '+str(root))
            conserved=summary['initial_stock']+summary['purchase_spend']-summary['sales']-summary['expiry_units']-summary['closing_stock']-summary['closing_pipeline']
            if abs(conserved)>1e-5:issues.append('Complete run stock conservation '+str(root))
    runs=pd.DataFrame(summaries);days=pd.DataFrame(daily);model=pd.DataFrame(calls)
    original=pd.read_csv(OUT/'summary.csv')
    sort=['dataset','scenario','seed','origin','arm']
    if len(runs)!=len(original):issues.append('Master summary membership mismatch')
    else:
        a=runs.sort_values(sort).reset_index(drop=True);b=original.sort_values(sort).reset_index(drop=True)
        if not a[sort].equals(b[sort]):issues.append('Master summary keys mismatch')
        for name in runs.select_dtypes(include='number').columns:
            if not np.allclose(a[name],b[name],atol=1e-6):issues.append('Master summary values mismatch '+name)
    complete=len(runs)==p['expected_runs'] and len(days)==p['expected_portfolio_days'] and len(calls)==p['expected_primary_fresh_model_calls']
    expected_keys={(dataset,scenario,seed,origin,day,arm)
        for dataset,info in p['datasets'].items() for scenario in p['scenarios']
        for seed in p['simulation_seeds'] for origin in info['origins']
        for day in range(info['days_per_origin']) for arm in p['arms']}
    if not decision_keys.issubset(expected_keys):issues.append('Unregistered decision grid keys')
    if complete and decision_keys!=expected_keys:issues.append('Registered matched grid differs')
    if receipt['status']=='COMPLETE' and not complete:issues.append('Declared completeness not supported by files')
    for field,value in [('runs',len(runs)),('portfolio_days',len(days)),('fresh_primary_model_calls',len(calls))]:
        if receipt[field]!=value:issues.append('Execution receipt count differs: '+field)
    out=OUT/'analysis';out.mkdir(exist_ok=True)
    runs.to_csv(out/'run_results.csv',index=False);days.to_csv(out/'daily_results.csv',index=False)
    model.to_csv(out/'model_calls.csv',index=False);pd.DataFrame(styles).to_csv(out/'source_accuracy_by_case.csv',index=False)
    pd.DataFrame(matches).to_csv(out/'matched_actions.csv',index=False)
    result={'status':'VERIFIED' if not issues else 'FAILED','at_utc':datetime.now(timezone.utc).isoformat(),
        'execution_complete':complete,'runs':len(runs),'portfolio_days':len(days),'series_days':len(days)*30,
        'fresh_primary_model_calls':len(calls),'unique_model_response_timestamps':len(created),'issues':issues,
        'checks':['Frozen source and data hashes','Exact registered matched grid','Same recorded demand for every arm',
            'Physical sales, stock and FIFO balance','Independent FIFO/supplier ledger replay from matched opening states',
            'Independent operating-cost recalculation',
            'Independent executed pack, MOQ, capacity and budget checks','Held actions never executed',
            'Every referenced model-call byte hash','Native model and generation settings','Unique fresh response timestamps',
            'Exactly three role calls per LLM portfolio decision','Source-field accuracy independently counted',
            'Per-run metrics recomputed from decision logs','Full inventory and pipeline conservation','Master summary byte values match local run files'],
        'protocol_sha256':sha(OUT/'protocol.json')}
    dump(out/'audit_receipt.json',result)
    if issues:raise RuntimeError(json.dumps(issues[:10]))
    return runs,days,model


def estimate(values):
    values=np.asarray(values,dtype=float)
    random=np.random.default_rng(20261009)
    draws=values[random.integers(0,len(values),size=(10000,len(values)))].mean(axis=1)
    return {'mean':float(values.mean()),'ci_low':float(np.quantile(draws,.025)),'ci_high':float(np.quantile(draws,.975)),'seeds':len(values)}


def analyze(runs,days,model):
    execution=json.loads((OUT/'execution_receipt.json').read_text())
    excluded_partial=0
    if execution['status']!='COMPLETE':
        valid=execution['balanced_seeds_complete']
        excluded_partial=int((~runs.seed.isin(valid)).sum())
        runs=runs[runs.seed.isin(valid)]
        if runs.empty:raise RuntimeError('No complete balanced seed round for analysis')
    sums=['demand','sales','operating_cost','holding_cost','shortage_cost','expiry_cost','expiry_units','initial_stock',
        'received_units','held_days','actual_violations','purchase_spend','source_correct_slots','source_exact_days',
        'priority_correct_days','critic_false_approvals','critic_false_holds','model_calls','schema_failures','input_tokens','output_tokens','total_agent_seconds','days']
    seeds=runs.groupby(['dataset','scenario','arm','seed'])[sums].sum().reset_index()
    seeds['fill_rate']=seeds.sales/seeds.demand
    seeds['cost_per_demand']=seeds.operating_cost/seeds.demand
    seeds['expiry_share']=seeds.expiry_units/(seeds.initial_stock+seeds.received_units)
    means=[]
    for (dataset,scenario,arm),g in seeds.groupby(['dataset','scenario','arm']):
        row={'dataset':dataset,'scenario':scenario,'arm':arm,'seeds':len(g)}
        for metric in ['fill_rate','cost_per_demand','expiry_share','operating_cost','holding_cost','shortage_cost','expiry_cost','held_days','purchase_spend']:
            result=estimate(g[metric]);row[metric]=result['mean'];row[metric+'_ci_low']=result['ci_low'];row[metric+'_ci_high']=result['ci_high']
        row['actual_violations']=int(g.actual_violations.sum());means.append(row)
    effects=[]
    for (dataset,scenario),g in seeds.groupby(['dataset','scenario']):
        agent=g[g.arm.eq('llm_agents')].set_index('seed')
        for comparator in ('conventional','structured_planner'):
            control=g[g.arm.eq(comparator)].set_index('seed');common=agent.index.intersection(control.index)
            for metric in ('fill_rate','cost_per_demand','expiry_share'):
                difference=agent.loc[common,metric]-control.loc[common,metric]
                scale=100 if metric in ('fill_rate','expiry_share') else 1
                result=estimate(difference*scale)
                row={'dataset':dataset,'scenario':scenario,'comparison':comparator,'metric':metric,**result,
                    'unit':'percentage_points' if scale==100 else 'cost_index_per_demand'}
                if metric=='cost_per_demand':
                    ratios=100*(agent.loc[common,metric]/control.loc[common,metric]-1)
                    ratio=estimate(ratios);row.update(relative_change_pct=ratio['mean'],relative_ci_low=ratio['ci_low'],relative_ci_high=ratio['ci_high'])
                effects.append(row)
    llm=days[days.arm.eq('llm_agents')]
    diagnostics=[]
    for dataset,g in llm.groupby('dataset'):
        mc=model[model.dataset.eq(dataset)]
        diagnostics.append({'dataset':dataset,'portfolio_days':len(g),'fresh_model_calls':len(mc),
            'exact_extraction_rate':float(g.source_exact.mean()),'field_accuracy':float(g.source_correct_slots.sum()/(13*len(g))),
            'priority_accuracy':float(g.priority_correct.mean()),'schema_validity':float(mc.schema_valid.mean()),
            'critic_false_approvals':int(g.critic_false_approval.sum()),'critic_false_holds':int(g.critic_false_hold.sum()),
            'held_days':int(g.held.sum()),'actual_violations':int(g.actual_violations.sum()),
            'mean_decision_seconds':float(g.agent_seconds.mean()),'median_decision_seconds':float(g.agent_seconds.median()),
            'p95_decision_seconds':float(g.agent_seconds.quantile(.95)),
            'input_tokens':int(mc.input_tokens.sum()),'output_tokens':int(mc.output_tokens.sum())})
    out=OUT/'analysis'
    seeds.to_csv(out/'seed_results.csv',index=False);pd.DataFrame(means).to_csv(out/'policy_means.csv',index=False)
    pd.DataFrame(effects).to_csv(out/'paired_effects.csv',index=False);pd.DataFrame(diagnostics).to_csv(out/'llm_diagnostics.csv',index=False)
    protocol=json.loads((OUT/'protocol.json').read_text());forecast_context=[]
    for dataset,info in protocol['datasets'].items():
        for origin in info['origins']:
            with np.load(OUT/f'data/{dataset}/origin_{origin}/panel_and_forecast.npz') as arrays:
                actual=arrays['sales'][:,origin:origin+7];predicted=arrays['forecast'][:,:7]
            forecast_context.append({'dataset':dataset,'origin':origin,'target':'Published sales proxy; no recovery',
                'model':'Shared LightGBM, not LLM','wape_pct':float(100*np.abs(actual-predicted).sum()/actual.sum()),
                'mae':float(np.abs(actual-predicted).mean()),'observations':actual.size})
    pd.DataFrame(forecast_context).to_csv(out/'shared_forecast_context.csv',index=False)
    dump(out/'analysis_summary.json',{'status':'COMPLETE','mean_results':means,'paired_effects':effects,'llm_diagnostics':diagnostics,
        'excluded_incomplete_seed_runs_from_inference':excluded_partial,
        'inference_note':'Origins aggregated inside each simulation seed; 10,000 paired bootstrap resamples. These intervals describe the simulated weeks and do not estimate a retailer population effect.',
        'reporting_note':'Negative operating-cost changes favour agents; positive fill changes favour agents. No predetermined superiority claim.'})
    print(json.dumps({'audit':'VERIFIED','runs':len(runs),'days':len(days),'fresh_calls':len(model),'effect_rows':len(effects)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-partial',action='store_true');args=parser.parse_args()
    analyze(*audit(args.allow_partial))
