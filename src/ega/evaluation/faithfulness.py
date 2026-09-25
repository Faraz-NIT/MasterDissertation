"""Replay, targeted interventions and fail-closed evidence deletion.

These measure externally logged evidence/tool faithfulness, never latent neural reasoning.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from ..store import ArtifactStore
from ..schemas import Snapshot,Forecast,ConstraintSet,Certificate,Plan,Autonomy
from ..config import ExperimentConfig
from ..quality import certify
from ..optimization import solve,policy_plan,build_problem,check_plan
from ..autonomy import decide_autonomy
from ..agents.orchestrator import POLICIES
from ..util import digest

def load_trace(run,day=None,ref=None):
    run=Path(run);store=ArtifactStore(run/'artifacts')
    if not ref:
        index=json.loads((run/'trace_index.json').read_text())
        candidates=[x for x in index if day is None or x['day']==day]
        if not candidates:store.close();raise ValueError('No trace for requested day')
        ref=candidates[0]['trace_ref']
    return store,store.get(ref),json.loads((run/'run_manifest.json').read_text())

def reconstruct(store,trace,manifest,delete=None):
    refs=trace['references'];required=['observe','certified_snapshot','certify_state','forecast','problem','propose']
    constraint_key='fallback_constraints' if 'fallback_constraints' in refs else 'ground_constraints'
    required.append(constraint_key)
    if delete in required:raise ValueError(f'Reconstruction refused: required artifact {delete} withheld')
    for key in required:
        if key not in refs:raise ValueError(f'No {key}; this was a held/incomplete decision')
    snapshot=Snapshot.model_validate(store.get(refs['certified_snapshot']))
    forecast=Forecast.model_validate(store.get(refs['forecast']))
    constraints=ConstraintSet.model_validate(store.get(refs[constraint_key]))
    config=ExperimentConfig.model_validate(manifest['config'])
    problem=build_problem(snapshot,forecast,constraints,config.solver,manifest['seed'])
    # Preserve the pinned configuration's JSON representation: a validated float
    # default may have originally serialized as 3000 rather than 3000.0.
    # Values are validated above; this restores wire identity, not solver inputs.
    problem['config']=manifest['config']['solver']
    return problem

def replay(run,day=None,ref=None):
    store,trace,manifest=load_trace(run,day,ref)
    try:
        refs=trace['references'];raw=Snapshot.model_validate(store.get(refs['observe']))
        original_cert=Certificate.model_validate(store.get(refs['certify_state']))
        config=ExperimentConfig.model_validate(manifest['config']);cert=certify(raw,config.gate)
        state_matches=(cert.quality==original_cert.quality and [c.model_dump() for c in cert.checks]==[c.model_dump() for c in original_cert.checks])
        result={'decision_id':trace['decision_id'],'chain_valid':store.verify_chain(),'state_certificate_matches':state_matches,
                'mode':'cached external evidence/tool replay; does not re-call the LLM or retrain forecasts'}
        if 'problem' not in refs or store.get(refs['propose'])['method']=='hold':
            plan=Plan.model_validate(store.get(refs['propose']))
            gate=Autonomy.model_validate(store.get(refs['autonomy']))
            result.update(held=True,action_matches=not(plan.orders or plan.transfers) and not gate.permitted,
                          replay_status='reproduced fail-closed held decision')
            return result
        problem=reconstruct(store,trace,manifest);saved=store.get(refs['problem'])
        recorded=Plan.model_validate(store.get(refs['propose']))
        action=solve(problem) if recorded.method=='stochastic_milp' else policy_plan(problem,config.forecast.service_quantile,recorded.method=='s_S')
        same_action=action.action_hash()==recorded.action_hash()
        result.update(held=False,problem_reconstruction_matches=digest(problem)==digest(saved),action_matches=same_action,
                      independent_violations=check_plan(action,problem),recorded_action_hash=recorded.action_hash(),replayed_action_hash=action.action_hash(),
                      objective_difference=None if action.objective is None or recorded.objective is None else action.objective-recorded.objective)
        result['replay_status']='exact action match' if same_action else 'action differs; inspect time-limit incumbent, tied optimum, or environment versions'
        return result
    finally:store.close()

def counterfactual(run,day=None,factor='budget',multiplier=0.5):
    store,trace,manifest=load_trace(run,day)
    try:
        problem=reconstruct(store,trace,manifest);altered=copy.deepcopy(problem)
        old=Plan.model_validate(store.get(trace['references']['propose']))
        if factor=='budget':altered['budget']*=multiplier
        elif factor=='capacity':
            for p in altered['supplier_parameters'].values():p['capacity']*=multiplier
        elif factor=='lead_time':altered['leads']=[[max(1,int(round(v*multiplier))) for v in row] for row in altered['leads']]
        elif factor=='forecast':altered['demand']=[[[v*multiplier for v in row] for row in w] for w in altered['demand']]
        elif factor=='eligibility':altered['parameters']['eligibility']=[0]*len(altered['series'])
        elif factor=='quality':
            cert=Certificate.model_validate(store.get(trace['references']['certify_state']))
            cert.quality=max(0,min(1,cert.quality*multiplier))
            cfg=ExperimentConfig.model_validate(manifest['config']);refs=trace['references']
            fc=Forecast.model_validate(store.get(refs['forecast']))
            ck='fallback_constraints' if 'fallback_constraints' in refs else 'ground_constraints'
            cs=ConstraintSet.model_validate(store.get(refs[ck]))
            decision=decide_autonomy(cert,old,problem,fc,cs,cfg.gate,enabled=POLICIES[trace['policy']]['gate'])
            return {'factor':factor,'multiplier':multiplier,'original_autonomy':trace['autonomy'],
                    'counterfactual_autonomy':decision.model_dump(),'interpretation':'Intervention on certificate quality only; hard failures remain non-overridable.'}
        else:raise ValueError('factor must be budget, capacity, lead_time, forecast, eligibility, or quality')
        new=solve(altered) if old.method=='stochastic_milp' else policy_plan(altered,ss=old.method=='s_S')
        return {'factor':factor,'multiplier':multiplier,'action_changed':new.action_hash()!=old.action_hash(),
                'original_action':{'orders':[x.model_dump() for x in old.orders],'transfers':[x.model_dump() for x in old.transfers]},
                'counterfactual_action':{'orders':[x.model_dump() for x in new.orders],'transfers':[x.model_dump() for x in new.transfers]},
                'violations':check_plan(new,altered),'counterfactual_solver':new.solver,
                'interpretation':'Nonbinding factors need not change the action; integer/coupled plans need not be globally monotonic.'}
    finally:store.close()

def deletion_test(run,day=None,artifact='forecast'):
    store,trace,manifest=load_trace(run,day)
    try:
        try:
            reconstruct(store,trace,manifest,delete=artifact)
            blocked=False
        except ValueError:blocked=True
        return {'deleted_artifact':artifact,'reconstruction_blocked':blocked,
                'interpretation':'Structural required-evidence deletion test, not a semantic LLM-context deletion or proof of causal importance.'}
    finally:store.close()

def trace_audit(run,day=None):
    store,trace,manifest=load_trace(run,day)
    try:
        refs=trace['references'];required=['observe','certify_state','certified_snapshot','propose','autonomy','receipt','outcome']
        if 'problem' in refs:required+=['forecast','fallback_constraints' if 'fallback_constraints' in refs else 'ground_constraints','problem']
        completeness=sum(k in refs for k in required)/len(required)
        cited=set(refs.values());consumed=set()
        for stage,payload in store.db.execute('SELECT stage,payload FROM events WHERE decision_id=?',(trace['decision_id'],)):
            consumed.update(json.loads(payload).get('inputs',[]))
        # Outputs are cited audit outcomes but not decision causes; exclude terminal outputs from causal precision.
        terminal={refs.get('outcome'),refs.get('receipt')};causal_citations=cited-terminal
        precision=len(causal_citations&consumed)/len(causal_citations) if causal_citations else 1
        recall=len(causal_citations&consumed)/len(consumed) if consumed else 1
        verified={k:store.get(ref) is not None for k,ref in refs.items()}
        return {'completeness':completeness,'consumption_precision':precision,'consumption_recall':recall,'artifacts_hash_verified':all(verified.values()),
                'note':'Consumption is instrumentation evidence, not proof that every consumed field was decisive. No neural chain-of-thought claims.'}
    finally:store.close()
