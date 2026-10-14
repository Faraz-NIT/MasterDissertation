"""LangChain extension of the previous replenishment agent; original decisions retained.

LCEL branches change delegation, not the model, prompt, forecast or optimisation
objective. The previous frozen nodes are reused as functions, never invoked via
the previous compiled LangGraph. No conversation memory or response cache is used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from langchain_core.runnables import RunnableBranch, RunnableLambda
from langchain_core.tools import StructuredTool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/architecture_study'))
import graph as previous
from architecture import base

os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'


def constrained_replenishment(target: list[float], urgency: list[float],
                              rules: dict, groups: list[int]) -> dict:
    """Calculate feasible replenishment with the unchanged constrained numerical planner."""
    proposed, solver = base.constrained_order(np.asarray(target), np.asarray(urgency),
                                              rules, np.asarray(groups))
    return {'proposed': proposed.tolist(), 'solver': solver}


PLANNING_TOOL = StructuredTool.from_function(constrained_replenishment)


def plan(state):
    target, urgency = state['env'].target(state['forecast'], state['residual_sd'],
                                         state['day'], state['rules'], state['groups'],
                                         state['priority'], True)
    if not state['source_ok'] or not state['route_ok'] or state['intake_review']:
        proposed, solver = np.zeros(30), {'feasible': False, 'reason': 'source_or_route_failed'}
    else:
        result = PLANNING_TOOL.invoke({'target': target.tolist(), 'urgency': urgency.tolist(),
                                      'rules': state['rules'], 'groups': state['groups'].tolist()})
        proposed, solver = np.asarray(result['proposed']), result['solver']
    return {'target': target, 'urgency': urgency, 'proposed': proposed, 'solver': solver,
            'node_trace': ['constrained_planning_tool']}


def step(function, name):
    """Merge the previous agent's partial updates into an explicitly traced LCEL state."""
    def apply(state):
        update = function(state)
        return {**state, **update,
                'node_trace': [*state.get('node_trace', []), *update.get('node_trace', [])]}
    return RunnableLambda(apply, name=name)


def build_chain():
    passthrough = RunnableLambda(lambda state: state, name='continue_without_model')
    supplier = RunnableBranch(
        (lambda state: state['intake_branch'] == 'extract',
         step(previous.extract, 'supplier_reader')),
        passthrough,
    )
    coordinator = RunnableBranch(
        (lambda state: state['arm'] == 'fixed_agents',
         step(previous.coordinator, 'original_llm_coordinator')),
        step(previous.route_policy, 'explicit_business_policy'),
    )
    review = RunnableBranch(
        (lambda state: state['arm'] == 'fixed_agents' or state['review_requested'],
         step(previous.review, 'critic_or_exception_reviewer')),
        passthrough,
    )
    return (
        step(previous.intake, 'supplier_intake')
        | supplier
        | step(previous.verify, 'source_verification')
        | coordinator
        | step(plan, 'numerical_planning_tool')
        | step(previous.validate, 'action_validation')
        | review
        | step(previous.release, 'release_gate')
    ).with_config({'run_name': 'replenishment_langchain_extension',
                   'tags': ['local-inference', 'selective-delegation']})


CHAIN = build_chain()
