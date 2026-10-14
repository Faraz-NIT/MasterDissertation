"""A LangGraph state machine for both fixed and selectively delegated agent workflows."""
from __future__ import annotations

import json
import operator
import os
from typing import Annotated, Any, TypedDict

import numpy as np
from langgraph.graph import END, START, StateGraph

from architecture import base, policy_route, release_permitted, structured_intake

# The experiment is local; no LangSmith service or external model API is used.
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'


class DecisionState(TypedDict, total=False):
    arm: str
    client: Any
    message: str
    rules: dict
    event: dict
    scenario: str
    day: int
    env: Any
    forecast: Any
    residual_sd: Any
    groups: Any
    before_stock: Any
    extracted: Any
    delegation: dict
    intake_branch: str
    intake_review: bool
    source_ok: bool
    source_slots: int
    source_failures: list
    route_ok: bool
    priority: str
    model_outputs: dict
    target: Any
    urgency: Any
    proposed: Any
    solver: dict
    action_failures: list
    valid: bool
    critic_approved: bool
    review_requested: bool
    permitted: bool
    committed: Any
    node_trace: Annotated[list[str], operator.add]


def intake(state):
    arm = state['arm']
    if arm == 'fixed_agents':
        route = {'route': 'three_llm_roles', 'reason': 'fixed_workflow'}
        branch, extracted, review = 'extract', None, False
    elif arm == 'structured_planner':
        route = {'route': 'authenticated_structured', 'reason': 'idealised_comparator'}
        branch, extracted, review = 'verify', state['rules'], False
    else:
        route = structured_intake(state['message'])
        branch = 'extract' if route['route'] == 'language' else 'verify'
        extracted, review = route['extracted'], route['route'] == 'review'
    return {'delegation': route, 'intake_branch': branch, 'extracted': extracted, 'intake_review': review,
            'model_outputs': {}, 'node_trace': ['supplier_intake']}


def extract(state):
    result = state['client'].ask('supplier', state['message'], f"day{state['day']}")
    return {'extracted': result, 'model_outputs': {'supplier': result}, 'node_trace': ['supplier_model']}


def verify(state):
    valid, slots, failures = base.verify_source(state['extracted'], state['rules'])
    return {'source_ok': valid, 'source_slots': slots, 'source_failures': failures,
            'model_outputs': {**state['model_outputs'], 'supplier': state['extracted']},
            'node_trace': ['source_verification']}


def coordinator(state):
    context = {'scenario': state['scenario'], 'active_promotion': state['event'].get('active_promotion'),
               'inventory_units': round(float(state['before_stock'].sum()), 2),
               'forecast_today': round(float(state['forecast'][:, state['day']].sum()), 2),
               'current_budget': state['rules']['budget'], 'source_verification': 'pass' if state['source_ok'] else 'fail',
               'supplier_rules': state['extracted']}
    result = state['client'].ask('planner', json.dumps(context), f"day{state['day']}")
    return {'route_ok': bool(result and result.get('tool') == 'constrained_order'),
            'priority': result['priority'] if result else 'balanced',
            'model_outputs': {**state['model_outputs'], 'planner': result}, 'node_trace': ['llm_coordinator']}


def route_policy(state):
    result = policy_route(state['event'])
    return {'route_ok': result['valid'], 'priority': result['priority'] or 'balanced',
            'model_outputs': {**state['model_outputs'], 'policy_router': result}, 'node_trace': ['policy_router']}


def plan(state):
    target, urgency = state['env'].target(state['forecast'], state['residual_sd'], state['day'],
                                         state['rules'], state['groups'], state['priority'], True)
    if not state['source_ok'] or not state['route_ok'] or state['intake_review']:
        proposed, solver = np.zeros(30), {'feasible': False, 'reason': 'source_or_route_failed'}
    else:
        proposed, solver = base.constrained_order(target, urgency, state['rules'], state['groups'])
    return {'target': target, 'urgency': urgency, 'proposed': proposed, 'solver': solver,
            'node_trace': ['constrained_planning_tool']}


def validate(state):
    failures = base.checks(state['proposed'], state['rules'], state['groups'])
    valid = release_permitted(state['source_ok'], state['route_ok'], state['solver'], failures, state['intake_review'])
    return {'action_failures': failures, 'valid': valid, 'critic_approved': True,
            'review_requested': state['arm'] == 'selective_agents' and not valid,
            'node_trace': ['action_validation']}


def review(state):
    failures = state['action_failures']
    context = {'source_verification': 'pass' if state['source_ok'] else 'fail',
               'tool_routing': 'pass' if state['route_ok'] else 'fail', 'solver_feasible': bool(state['solver']['feasible']),
               'action_checks': {'pack': 'fail' if 'pack_size' in failures else 'pass',
                                'moq': 'fail' if 'minimum_order' in failures else 'pass',
                                'capacity': 'fail' if any(f.startswith('capacity') for f in failures) else 'pass',
                                'budget': 'fail' if 'budget' in failures else 'pass',
                                'nonnegative': 'fail' if 'nonnegative_quantities' in failures else 'pass'},
               'proposed_units': int(state['proposed'].sum()), 'budget': state['rules']['budget']}
    result = state['client'].ask('critic', json.dumps(context), f"day{state['day']}")
    return {'critic_approved': bool(result and result['verdict'] == 'approve'),
            'model_outputs': {**state['model_outputs'], 'critic': result}, 'node_trace': ['llm_review']}


def release(state):
    permitted = bool(state['valid'] and state['critic_approved'])
    return {'permitted': permitted, 'committed': state['proposed'] if permitted else np.zeros(30),
            'node_trace': ['release_gate']}


def build_graph():
    graph = StateGraph(DecisionState)
    for name, node in [('supplier_intake', intake), ('supplier_model', extract), ('source_verification', verify),
                       ('llm_coordinator', coordinator), ('policy_router', route_policy),
                       ('constrained_planning_tool', plan), ('action_validation', validate),
                       ('llm_review', review), ('release_gate', release)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'supplier_intake')
    graph.add_conditional_edges('supplier_intake', lambda s: s['intake_branch'],
                                {'extract': 'supplier_model', 'verify': 'source_verification'})
    graph.add_edge('supplier_model', 'source_verification')
    graph.add_conditional_edges('source_verification', lambda s: 'llm' if s['arm'] == 'fixed_agents' else 'policy',
                                {'llm': 'llm_coordinator', 'policy': 'policy_router'})
    graph.add_edge('llm_coordinator', 'constrained_planning_tool')
    graph.add_edge('policy_router', 'constrained_planning_tool')
    graph.add_edge('constrained_planning_tool', 'action_validation')
    graph.add_conditional_edges('action_validation',
                                lambda s: 'review' if s['arm'] == 'fixed_agents' or s['review_requested'] else 'release',
                                {'review': 'llm_review', 'release': 'release_gate'})
    graph.add_edge('llm_review', 'release_gate')
    graph.add_edge('release_gate', END)
    return graph.compile()


GRAPH = build_graph()
