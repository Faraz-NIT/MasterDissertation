"""Delegation, guarded release and preservation of the original planning behaviour."""
import sys
from pathlib import Path

import numpy as np
from langchain_core.callbacks import BaseCallbackHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/langchain_extension'))
from chain import CHAIN, PLANNING_TOOL, previous


def agreement():
    return {'rules': [{'supplier': f'S{i+1}', 'pack': p, 'moq': p*2,
                       'lead_days': i+1, 'capacity': c}
                      for i, (p, c) in enumerate([(2,14),(4,28),(6,42)])], 'budget':65}


class Client:
    def __init__(self, supplied):
        self.supplied, self.roles = supplied, []
    def ask(self, role, content, name):
        self.roles.append(role)
        return (self.supplied if role == 'supplier' else
                {'tool':'constrained_order','priority':'balanced'} if role == 'planner' else
                {'verdict':'approve'})


def inputs(style, client, arm='selective_agents', event=None):
    data = {'dataset':'M5','series_ids':list(map(str,range(30))),
            'historical_mean':np.ones(30)*2}
    env = previous.base.Inventory(data,901)
    env.begin(0)
    return {'arm':arm,'client':client,
            'message':previous.base.supplier_message(agreement(),0,style),
            'rules':agreement(),'event':{'active_promotion':True} if event is None else event,
            'scenario':'promotion','day':0,'env':env,'forecast':np.ones((30,14))*3,
            'residual_sd':np.zeros(30),'groups':np.arange(30)%3,
            'before_stock':env.stock(),'node_trace':[]}


def test_langchain_retains_previous_graph_behaviour_across_roles_and_formats():
    for arm in ['fixed_agents','selective_agents','structured_planner']:
        for style in range(3):
            left, right = Client(agreement()), Client(agreement())
            result = CHAIN.invoke(inputs(style,left,arm))
            original = previous.GRAPH.invoke(inputs(style,right,arm))
            assert np.array_equal(result['committed'],original['committed'])
            assert result['node_trace'] == original['node_trace']
            assert result['priority'] == original['priority']
            assert result['permitted'] == original['permitted']
            assert left.roles == right.roles


def test_table_bypasses_llm_but_prose_uses_supplier_reader():
    for style, roles in [(0,['supplier']),(1,['supplier']),(2,[])]:
        client = Client(agreement())
        result = CHAIN.invoke(inputs(style,client))
        assert client.roles == roles and result['permitted']
        assert result['priority'] == 'service_first'
        assert not previous.base.checks(result['committed'],agreement(),np.arange(30)%3)


def test_approving_model_cannot_override_bad_source_or_unknown_event():
    wrong = agreement(); wrong['budget'] = 999
    for supplied,event in [(wrong,{'active_promotion':True}), (agreement(),{})]:
        client = Client(supplied)
        result = CHAIN.invoke(inputs(0,client,event=event))
        assert result['review_requested'] and not result['permitted']
        assert not result['committed'].any() and client.roles == ['supplier','critic']


def test_malformed_table_is_held_without_supplier_llm_or_planner_tool():
    client = Client(agreement()); state = inputs(2,client)
    state['message'] = state['message'].replace('S2 | 4 | 8 | 2 | 28','S2 | ? | 8 | 2 | 28')
    result = CHAIN.invoke(state)
    assert result['delegation']['route'] == 'review'
    assert not result['permitted'] and client.roles == ['critic']
    assert result['solver']['reason'] == 'source_or_route_failed'


def test_numerical_planner_is_an_actual_langchain_tool():
    class Recorder(BaseCallbackHandler):
        def __init__(self): self.names = []
        def on_tool_start(self, serialized, input_str, **kwargs):
            self.names.append(serialized['name'])
    recorder = Recorder()
    result = PLANNING_TOOL.invoke({'target':[1.]*30,'urgency':[1.]*30,
                                  'rules':agreement(),'groups':(np.arange(30)%3).tolist()},
                                 config={'callbacks':[recorder]})
    assert recorder.names == ['constrained_replenishment']
    assert not previous.base.checks(result['proposed'],agreement(),np.arange(30)%3)
