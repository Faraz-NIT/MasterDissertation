"""Recorded-response regression over all prior decisions; explicitly not live inference."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parent))
from chain import CHAIN,base
from validation_run import OUT,PRIOR,now


class RecordedClient:
    def __init__(self,record):
        self.record,self.roles = record,[]
    def ask(self,role,content,name):
        self.roles.append(role)
        call = next(c for c in self.record['model_call_records'] if c['role'] == role)
        native = json.loads((PRIOR/call['path']).read_text())
        assert native['request']['messages'][-1]['content'] == content
        assert native['name'] == name
        return self.record['model_outputs'][role]


def replay():
    destination = OUT/'development/recorded_response_replay.json'
    if destination.exists(): raise FileExistsError('Preserve the replay receipt')
    assert json.loads((PRIOR/'analysis/audit_receipt.json').read_text())['status'] == 'VERIFIED'
    frames,checks,model_outputs = {},[],0
    for path in sorted((PRIOR/'runs').glob('*/decisions.jsonl')):
        records = [json.loads(line) for line in path.read_text().splitlines()]
        first = records[0]['row']; key = (first['dataset'],first['origin'])
        if key not in frames:
            folder = PRIOR/f'data/{key[0]}/origin_{key[1]}'
            data = json.loads((folder/'catalog.json').read_text())
            with np.load(folder/'panel_and_forecast.npz') as arrays:
                data.update({name:arrays[name] for name in arrays.files})
            frames[key] = data
        data = frames[key]
        worlds = json.loads((path.parent/'demand_world.json').read_text())['quantities']
        inventories = {arm:base.Inventory(data,first['seed']) for arm in ['fixed_agents','selective_agents','structured_planner']}
        for record in records:
            row = record['row']; day = row['day']; env = inventories[row['arm']]
            env.begin(day)
            assert np.allclose(env.stock(),record['stock_before'])
            forecast = data['forecast'].copy()
            if record['business_event']['active_promotion']: forecast[:,day:] *= 1.3
            client = RecordedClient(record)
            result = CHAIN.invoke({'arm':row['arm'],'client':client,'message':record['source_text'],
                                   'rules':record['authoritative_contract'],'event':record['business_event'],
                                   'scenario':row['scenario'],'day':day,'env':env,'forecast':forecast,
                                   'residual_sd':data['residual_sd'],'groups':data['groups'],
                                   'before_stock':env.stock(),'node_trace':[]})
            assert result['node_trace'] == record['langgraph_node_trace']
            assert result['priority'] == record['chosen_priority']
            assert result['source_ok'] == bool(row['source_exact'])
            assert result['permitted'] == bool(not row['held'])
            assert result['model_outputs'] == record['model_outputs']
            for name in ['proposed','committed']:
                assert np.array_equal(result[name],record[name])
            assert client.roles == [c['role'] for c in record['model_call_records']]
            model_outputs += len(client.roles)
            if result['permitted']: env.execute(day,result['committed'],record['authoritative_contract'],data['groups'])
            outcome = env.end(day,np.asarray(worlds)[:,day])
            for name,value in outcome.items():
                assert np.allclose(value,record['outcome'][name])
            checks.append({**{k:row[k] for k in ['dataset','scenario','seed','origin','day','arm']},
                           'identical_actions':True,'identical_priority':True,'identical_role_path':True})
    assert len(checks) == 7560 and model_outputs == 9240
    pd.DataFrame(checks).to_csv(OUT/'development/recorded_response_replay.csv',index=False)
    receipt = {'status':'PASS','at_utc':now(),'portfolio_decisions':len(checks),'native_inference_calls':0,
               'recorded_model_outputs_used':model_outputs,'all_actions_priorities_paths_and_inventory_outcomes_identical':True,
               'scope':'Software regression only; archived answers are supplied to both implementations',
               'does_not_establish_fresh_model_reproducibility':True,
               'source_protocol_sha256':base.sha(PRIOR/'protocol.json')}
    base.dump(destination,receipt)
    print(json.dumps(receipt))


if __name__ == '__main__':
    replay()
