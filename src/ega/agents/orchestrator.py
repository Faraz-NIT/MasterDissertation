from __future__ import annotations
from dataclasses import dataclass
from .roles import StateReconciliationAgent,DemandForecastAgent,SupplierConstraintAgent,OptimizationAgent,RiskCriticAgent
from .llm import LLMClient,ModelUnavailable
from ..schemas import ConstraintSet,Plan,Autonomy,Check,Verdict
from ..constraints import extract_templates,verify_constraints
from ..optimization import build_problem
from ..autonomy import decide_autonomy
from ..util import digest

POLICIES={
 'B1':{'forecast':'seasonal_naive','mode':'policy','gate':False,'critic':False,'llm':False},
 'B2':{'forecast':'lightgbm','mode':'ss','gate':False,'critic':False,'llm':False},
 'B3':{'forecast':'deep','mode':'milp','gate':False,'critic':False,'llm':False},
 'B4':{'forecast':'deep','mode':'milp','gate':True,'critic':False,'llm':False},
 'B5':{'forecast':'chronos','mode':'policy','gate':False,'critic':False,'llm':False},
 'B6':{'forecast':'deep','mode':'milp','gate':True,'critic':True,'llm':True,'single':True},
 'B7':{'forecast':'deep','mode':'milp','gate':True,'critic':True,'llm':True,'free_form':True},
 'B8':{'forecast':'deep','mode':'milp','gate':True,'critic':False,'llm':True},
 'B9':{'forecast':'deep','mode':'milp','gate':False,'critic':True,'llm':True},
 'B10':{'forecast':'deep','mode':'milp','gate':True,'critic':True,'llm':True},
 'D0':{'forecast':'seasonal_naive','mode':'milp','gate':False,'critic':False,'llm':False},
 'D1':{'forecast':'seasonal_naive','mode':'milp','gate':True,'critic':True,'llm':False}}

@dataclass
class Decision:
    decision_id:str
    plan:Plan
    autonomy:Autonomy
    trace:dict
    certificate:object
    problem:dict|None

class OrchestratorAutonomyAgent:
    def __init__(self,policy,model,config,store):
        self.policy=policy;self.spec=POLICIES[policy];self.model=model;self.config=config;self.store=store
        self.client=LLMClient(config.llm,store) if self.spec['llm'] else None
        self.holds=0
    def run(self,snapshot,documents,decision_id,seed):
        cfg=self.config;spec=self.spec;refs={};consumed=[];stages=[];used_fallback=False
        call_start=self.client.calls if self.client else 0;token_start=self.client.tokens if self.client else 0
        error_start=self.client.errors if self.client else 0;ref_start=len(self.client.refs) if self.client else 0
        def record(stage,obj,inputs=()):
            ref=self.store.put(obj);refs[stage]=ref;consumed.extend(inputs);stages.append(stage)
            self.store.event(decision_id,stage,{'inputs':list(inputs),'output':ref})
            return ref
        raw_ref=record('observe',snapshot)
        sources_ref=record('source_documents',[d.payload() for d in documents])
        client=self.client;free=spec.get('free_form',False);single=spec.get('single',False)
        fallback_reasons=[]
        try:
            memory=self.store.memory_read(list(snapshot.aliases),snapshot.lineage.day) if cfg.llm.use_memory else []
            cert=StateReconciliationAgent().run(snapshot,cfg.gate,None if single else client,memory,free)
        except ModelUnavailable as exc:
            from ..quality import certify
            cert=certify(snapshot,cfg.gate);fallback_reasons.append(str(exc));client=None;used_fallback=True
        cert_ref=record('certify_state',cert,[raw_ref])
        snap=snapshot.model_copy(deep=True);snap.lineage.certificate_hash=cert_ref
        snap_ref=record('certified_snapshot',snap,[raw_ref,cert_ref])
        empty=Plan(lineage=snap.lineage,method='hold',orders=[],transfers=[],objective=None,components={},solver={'status':'not_run','feasible':False},active_constraints=[])
        plan=empty;forecast=None;cs=None;problem=None;verdict=None
        blocked=(spec['gate'] and cert.hard_fail) or (used_fallback and cfg.llm.on_failure=='hold')
        if not blocked:
            try:
                forecast=DemandForecastAgent(self.model).run(snap,cfg.solver,seed)
                forecast_ref=record('forecast',forecast,[snap_ref,cert_ref])
                cs=SupplierConstraintAgent().run(snap,documents,cfg.gate,client,free,single,cert)
                cs_ref=record('ground_constraints',cs,[snap_ref,sources_ref])
                if cs.issues:raise ValueError('Constraint escalation: '+'; '.join(cs.issues))
                problem=build_problem(snap,forecast,cs,cfg.solver,seed)
                problem_ref=record('problem',problem,[snap_ref,forecast_ref,cs_ref])
                plan=OptimizationAgent().run(problem,cfg.forecast.service_quantile,spec['mode'],None if single else client,free)
                plan_ref=record('propose',plan,[problem_ref])
                if spec['critic']:
                    verdict=RiskCriticAgent().run(plan,problem,documents,None if single else client,free)
                    record('verify',verdict,[plan_ref,problem_ref,sources_ref])
            except ModelUnavailable as exc:
                fallback_reasons.append(str(exc));used_fallback=True
                if cfg.llm.on_failure=='deterministic' and not cert.hard_fail:
                    # Explicit operational fallback, never silently count this as successful B10 agent reasoning.
                    cs=verify_constraints(extract_templates(documents,snap.lineage),snap.series,documents,snap.lineage.day,cfg.gate.min_confidence)
                    cs_ref=record('fallback_constraints',cs,[sources_ref,snap_ref])
                    if not cs.issues and forecast is not None:
                        problem=build_problem(snap,forecast,cs,cfg.solver,seed)
                        problem_ref=record('problem',problem,[snap_ref,refs['forecast'],cs_ref])
                        plan=OptimizationAgent().run(problem,cfg.forecast.service_quantile,spec['mode'])
                        record('propose',plan,[problem_ref])
                        verdict=RiskCriticAgent().run(plan,problem,documents)
                        record('verify',verdict,[refs['propose'],problem_ref])
                    else:plan=empty
                else:plan=empty;problem=None
            except (ValueError,RuntimeError) as exc:
                fallback_reasons.append(str(exc));plan=empty;problem=None
        if problem is None:
            autonomy=Autonomy(level='advisory',permitted=False,reasons=fallback_reasons or ['State hard failure; hold is not a zero-order recommendation'],
                              inputs={'quality':cert.quality,'policy_version':cfg.gate.version},urgent=self.holds>=cfg.gate.hold_budget)
        else:
            autonomy=decide_autonomy(cert,plan,problem,forecast,cs,cfg.gate,self.holds,spec['gate'])
            if verdict and verdict.decision!='pass':
                autonomy.permitted=False;autonomy.level='approval';autonomy.required_approvals=1
                autonomy.reasons.append('Critic '+verdict.decision)
            if plan.method=='hold' or (spec['mode']=='milp' and not plan.solver.get('feasible')):
                autonomy.permitted=False;autonomy.level='advisory';autonomy.reasons.append('No certified feasible plan')
        self.holds=0 if autonomy.permitted else self.holds+1
        # Keep earlier proposals in immutable events, but point the final trace to the selected action.
        if 'propose' not in refs:
            record('propose',plan,[cert_ref])
        elif Plan.model_validate(self.store.get(refs['propose'])).action_hash()!=plan.action_hash():
            record('propose',plan,[refs['propose'],cert_ref])
        gate_inputs=[refs[k] for k in ['certify_state','propose','problem','forecast','ground_constraints','fallback_constraints','verify'] if k in refs]
        auto_ref=record('autonomy',autonomy,gate_inputs)
        trace={'schema_version':'trace-v1','decision_id':decision_id,'policy':self.policy,
               'effective_policy':self.policy+('-fallback' if used_fallback else '')+('-forecast-override' if cfg.forecast_override else ''),
               'day':snapshot.lineage.day,'lineage':snap.lineage.model_dump(),'references':refs,'stages':stages,
               'consumed_refs':sorted(set(consumed)),'plan_action_hash':plan.action_hash(),'autonomy':autonomy.model_dump(),
               'fallback':used_fallback,'errors':fallback_reasons,'model_name':self.model.name,
               'llm':{'calls':self.client.calls-call_start if self.client else 0,
                      'tokens':self.client.tokens-token_start if self.client else 0,
                      'errors':self.client.errors-error_start if self.client else 0,
                      'artifacts':self.client.refs[ref_start:] if self.client else []},
               'execution':None,'outcome':None}
        return Decision(decision_id,plan,autonomy,trace,cert,problem)
