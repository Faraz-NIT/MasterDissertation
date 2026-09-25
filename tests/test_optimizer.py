import copy
import numpy as np
import pytest
from ega.optimization import solve,check_plan,policy_plan,build_problem
from ega.experiment import true_problem_for
from ega.constraints import synthetic_contracts,render_templates
from ega.schemas import Order,Transfer,Plan


def test_milp_feasible_and_objective(problem):
    plan=solve(problem)
    assert plan.solver['feasible'] and not check_plan(plan,problem)
    assert plan.solver['max_primal_violation']<1e-5
    assert plan.objective==pytest.approx(plan.solver['raw_objective'],abs=1e-4)
    assert plan.objective==pytest.approx(plan.components['expected_cost']+problem['config']['risk_weight']*plan.components['cvar'])


def test_pack_and_moq_constraints(problem):
    p=copy.deepcopy(problem);p['on_hand']=[0,0];p['receipts']=(np.asarray(p['receipts'])*0).tolist()
    plan=solve(p)
    assert plan.solver['feasible'] and not check_plan(plan,p)
    for o in plan.orders:
        i=next(j for j,s in enumerate(p['series']) if s['series_id']==o.series_id)
        assert o.quantity%p['parameters']['pack'][i]==0 and o.quantity>=p['parameters']['moq'][i]


def test_zero_budget_no_orders(problem):
    p=copy.deepcopy(problem);p['budget']=0
    plan=solve(p);assert plan.solver['feasible']
    assert sum(o.quantity for o in plan.orders)==0


def test_ineligible_never_receives(problem):
    p=copy.deepcopy(problem);p['parameters']['eligibility']=[0,0]
    plan=solve(p);assert not plan.orders and not plan.transfers


def test_foreign_aggregate_moq(snapshot,model,config):
    raw=synthetic_contracts(snapshot.series,snapshot.prices,[True]*len(snapshot.series),140,7,'foreign_unit_moq',True,3000)
    p=true_problem_for(snapshot,render_templates(raw),model,config,7)
    p['on_hand']=[0,0];p['receipts']=(np.asarray(p['receipts'])*0).tolist()
    plan=solve(p);assert plan.solver['feasible'] and not check_plan(plan,p)


def test_bad_action_detected(problem):
    s=problem['series'][0]
    p=Plan(lineage=problem['lineage'],method='test',orders=[Order(series_id=s['series_id'],supplier=s['supplier'],quantity=100000)],transfers=[],objective=None,components={},solver={},active_constraints=[])
    assert check_plan(p,problem)


def test_solver_reproducible_action(problem):
    assert solve(problem).action_hash()==solve(problem).action_hash()


def test_policy_transparent_line_level(problem):
    assert policy_plan(problem).method=='order_up_to'
