"""Checks at the boundaries that determine which decisions can execute."""
import importlib.util
import sys
import numpy as np
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/architecture_study/architecture.py'
spec = importlib.util.spec_from_file_location('selective_architecture', SCRIPT)
arch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arch)
sys.path.insert(0, str(SCRIPT.parent))
from graph import GRAPH


def agreement():
    return {'rules': [{'supplier': f'S{i+1}', 'pack': p, 'moq': p*2, 'lead_days': i+1,
                       'capacity': c} for i, (p, c) in enumerate([(2, 14), (4, 28), (6, 42)])], 'budget': 65}


def test_table_parser_reads_message_without_authenticated_values():
    truth = agreement()
    message = arch.base.supplier_message(truth, 2, 2)
    result = arch.structured_intake(message)
    assert result['route'] == 'structured' and result['extracted'] == truth
    changed = message.replace('S1 | 2 | 4 | 1 | 14', 'S1 | 2 | 4 | 1 | 13')
    result = arch.structured_intake(changed)
    assert result['extracted']['rules'][0]['capacity'] == 13
    assert not arch.base.verify_source(result['extracted'], truth)[0]


def test_prose_is_delegated_and_malformed_declared_tables_are_held():
    for style in [0, 1]:
        assert arch.structured_intake(arch.base.supplier_message(agreement(), 1, style))['route'] == 'language'
    message = arch.base.supplier_message(agreement(), 1, 2)
    for broken in [message.replace('S2 |', 'S1 |'), message.replace('S2 | 4 | 8 | 2 | 28\n', ''),
                   message.replace('S3 | 6 | 12 | 3 | 42', 'S3 | ? | 12 | 3 | 42'),
                   message + '\nS1 | 2 | 4 | 1 | 999', message + '\n' + message.splitlines()[-1]]:
        assert arch.structured_intake(broken)['route'] == 'review'


def test_router_uses_only_known_event_and_refuses_ambiguous_types():
    assert arch.policy_route({'active_promotion': True})['priority'] == 'service_first'
    assert arch.policy_route({'active_promotion': False})['priority'] == 'balanced'
    for event in [{}, {'active_promotion': 'false'}, {'active_promotion': 0}, None]:
        assert arch.policy_route(event)['review_required']
    left = arch.policy_route({'active_promotion': True, 'future_sales': 0})
    right = arch.policy_route({'active_promotion': True, 'future_sales': 999999})
    assert left == right


def test_failed_checks_cannot_be_overridden_by_a_model_approval():
    assert arch.release_permitted(True, True, {'feasible': True}, [])
    assert not arch.release_permitted(False, True, {'feasible': True}, [])
    assert not arch.release_permitted(True, False, {'feasible': True}, [])
    assert not arch.release_permitted(True, True, {'feasible': False}, [])
    assert not arch.release_permitted(True, True, {'feasible': True}, ['budget'])
    assert not arch.release_permitted(True, True, {'feasible': True}, [], intake_review=True)


class StubClient:
    def __init__(self, supplied):
        self.supplied, self.calls = supplied, []
    def ask(self, role, content, name):
        self.calls.append(role)
        return self.supplied if role == 'supplier' else {'verdict': 'approve'} if role == 'critic' else {'tool': 'constrained_order', 'priority': 'balanced'}


def graph_input(style, client):
    data = {'dataset': 'M5', 'series_ids': list(map(str, range(30))), 'historical_mean': np.ones(30)*2}
    env = arch.base.Inventory(data, 901)
    env.begin(0)
    return {'arm': 'selective_agents', 'client': client, 'message': arch.base.supplier_message(agreement(), 0, style),
            'rules': agreement(), 'event': {'active_promotion': True}, 'scenario': 'promotion', 'day': 0,
            'env': env, 'forecast': np.ones((30,14))*3, 'residual_sd': np.zeros(30), 'groups': np.arange(30)%3,
            'before_stock': env.stock(), 'node_trace': []}


def test_langgraph_delegates_prose_but_executes_valid_table_without_model_calls():
    for style, expected_calls in [(0,['supplier']), (1,['supplier']), (2,[])]:
        client = StubClient(agreement())
        result = GRAPH.invoke(graph_input(style, client))
        assert result['permitted'] and result['priority'] == 'service_first'
        assert client.calls == expected_calls
        assert result['node_trace'][0] == 'supplier_intake' and result['node_trace'][-1] == 'release_gate'
        assert not arch.base.checks(result['committed'],agreement(),np.arange(30)%3)


def test_langgraph_holds_failed_source_even_when_review_model_approves():
    wrong = agreement(); wrong['budget'] = 999
    client = StubClient(wrong)
    result = GRAPH.invoke(graph_input(0, client))
    assert result['review_requested'] and not result['permitted'] and not result['committed'].any()
    assert client.calls == ['supplier','critic']
    client = StubClient(agreement()); inputs = graph_input(2, client); inputs['event'] = {}
    result = GRAPH.invoke(inputs)
    assert not result['permitted'] and result['review_requested'] and not result['committed'].any()
