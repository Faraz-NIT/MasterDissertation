"""Independent ledger replay adapted only for new arm names from the previous verified audit.
Does not import the evaluated inventory simulator.
"""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'study_results/architecture_study_20261013'
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
    for arm in ('fixed_agents','selective_agents','structured_planner'):
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

