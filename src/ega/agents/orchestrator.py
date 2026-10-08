from __future__ import annotations
from dataclasses import dataclass
from .roles import StateReconciliationAgent,DemandForecastAgent,SupplierConstraintAgent,OptimizationAgent,RiskCriticAgent
from .llm import LLMClient,ModelUnavailable,RecoverySelection
from ..schemas import ConstraintSet,Plan,Autonomy,Check,Verdict
from ..constraints import extract_templates,verify_constraints
from ..optimization import build_problem
from ..autonomy import decide_autonomy
from ..util import digest
from ..quality import certify

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
    def __init__(self,policy,model,config,store,optimizer=None):
        self.policy=policy;self.spec=POLICIES[policy];self.model=model;self.config=config;self.store=store
        self.client=LLMClient(config.llm,store) if self.spec['llm'] else None
        self.optimizer=optimizer if optimizer is not None else OptimizationAgent()
        self.holds=0
        self.grounding_v2=None
        if config.agent_v2.enabled:
            from .grounding_v2 import GroundingV2Agent
            context=digest({'gate':config.gate.model_dump(),'agent_v2':config.agent_v2.model_dump()})
            self.grounding_v2=GroundingV2Agent(
                cache_enabled=config.agent_v2.cache_enabled, cache_path=config.agent_v2.cache_path,
                model_revision=config.llm.model_revision if self.client else 'deterministic-source-parser',
                context_version=context, semantic_retries=config.agent_v2.semantic_retries,
                compact_output=config.agent_v2.compact_output,
                baseline_full_parser=not self.spec['llm'])
    def run(self,snapshot,documents,decision_id,seed):
        cfg=self.config;spec=self.spec;refs={};consumed=[];stages=[];used_fallback=False
        v2_audit_index=0
        call_start=self.client.calls if self.client else 0;token_start=self.client.tokens if self.client else 0
        error_start=self.client.errors if self.client else 0;ref_start=len(self.client.refs) if self.client else 0
        def record(stage,obj,inputs=()):
            ref=self.store.put(obj);refs[stage]=ref;consumed.extend(inputs);stages.append(stage)
            self.store.event(decision_id,stage,{'inputs':list(inputs),'output':ref})
            return ref
        def record_v2(stage,obj,inputs=()):
            nonlocal v2_audit_index
            v2_audit_index+=1
            return record(f'v2_{v2_audit_index:04d}_{stage}',obj,inputs)
        raw_ref=record('observe',snapshot)
        sources_ref=record('source_documents',[d.payload() for d in documents])
        client=self.client;free=spec.get('free_form',False);single=spec.get('single',False)
        if client and cfg.agent_v2.enabled:client.audit_decision_id=decision_id
        fallback_reasons=[]
        recovery_report=None;working_snapshot=snapshot
        if cfg.agent_v2.enabled:
            observed_cert=certify(snapshot,cfg.gate)
            observed_cert_ref=record('observed_certificate',observed_cert,[raw_ref])
            requested='hold'
            if cfg.agent_v2.state_recovery and observed_cert.hard_fail:
                if client and cfg.agent_v2.llm_recovery_selection:
                    failures=[c.model_dump() for c in observed_cert.checks if c.outcome=='hard_fail']
                    allowed={c['name'] for c in failures}
                    try:
                        selection=client.ask('evidence recovery tool selector',{
                            'anomalies':failures,'allowed_evidence_refs':sorted(allowed),
                            'allowed_tools':['reconcile_current_inventory','hold'],
                            'source_inventory_complete':all(r.source_quantity is not None for r in snapshot.inventory),
                            'stage_days':snapshot.stage_days,'decision_day':snapshot.lineage.day,
                            'task':('Select reconcile_current_inventory only for inventory_distribution_shift and '
                                    'stock_movement_balance failures with complete current source inventory. '
                                    'The tool checks source/ledger agreement and independently recertifies. '
                                    'Select hold for stale or absent sources. Cite the named anomaly checks.')},RecoverySelection)
                        selection_ref=record('recovery_selection',selection,[observed_cert_ref,raw_ref])
                        if set(selection.evidence_refs)<=allowed and selection.evidence_refs:
                            requested=selection.requested_tool
                        else:fallback_reasons.append('Recovery selector cited missing or unallowlisted evidence')
                    except ModelUnavailable as exc:
                        fallback_reasons.append(str(exc))
                        record('recovery_selection_failure',{'error':str(exc)},[observed_cert_ref])
                else:
                    requested='reconcile_current_inventory'
                    record('recovery_selection',{'requested_tool':requested,'source':'deterministic_policy'},[observed_cert_ref])
                if requested=='reconcile_current_inventory':
                    from ..recovery import recover_snapshot
                    working_snapshot,recovery_report=recover_snapshot(snapshot,cfg.gate,record_v2)
            record('recovery_status',{'enabled':cfg.agent_v2.state_recovery,'requested_tool':requested,
                                     'result':recovery_report},[raw_ref,observed_cert_ref])
            working_ref=record('reconciled_snapshot',working_snapshot,[raw_ref,refs['recovery_status']])
            cert=certify(working_snapshot,cfg.gate)
        else:
            try:
                memory=self.store.memory_read(list(snapshot.aliases),snapshot.lineage.day) if cfg.llm.use_memory else []
                cert=StateReconciliationAgent().run(snapshot,cfg.gate,None if single else client,memory,free)
            except ModelUnavailable as exc:
                cert=certify(snapshot,cfg.gate);fallback_reasons.append(str(exc));client=None;used_fallback=True
        cert_ref=record('certify_state',cert,[refs.get('reconciled_snapshot',raw_ref)])
        snap=working_snapshot.model_copy(deep=True);snap.lineage.certificate_hash=cert_ref
        snap_ref=record('certified_snapshot',snap,[refs.get('reconciled_snapshot',raw_ref),cert_ref])
        empty=Plan(lineage=snap.lineage,method='hold',orders=[],transfers=[],objective=None,components={},solver={'status':'not_run','feasible':False},active_constraints=[])
        plan=empty;forecast=None;cs=None;problem=None;verdict=None
        blocked=(spec['gate'] and cert.hard_fail) or (used_fallback and cfg.llm.on_failure=='hold')
        if not blocked:
            try:
                forecast=DemandForecastAgent(self.model).run(snap,cfg.solver,seed)
                forecast_ref=record('forecast',forecast,[snap_ref,cert_ref])
                if self.grounding_v2:
                    cs=self.grounding_v2.run(documents,snap.lineage,snap.series,snap.lineage.day,
                        client=client,record=record_v2,confidence_threshold=cfg.gate.min_confidence)
                else:cs=SupplierConstraintAgent().run(snap,documents,cfg.gate,client,free,single,cert)
                cs_ref=record('ground_constraints',cs,[snap_ref,sources_ref])
                if cs.issues:raise ValueError('Constraint escalation: '+'; '.join(cs.issues))
                problem=build_problem(snap,forecast,cs,cfg.solver,seed)
                problem_ref=record('problem',problem,[snap_ref,forecast_ref,cs_ref])
                route_client=None if single or (cfg.agent_v2.enabled and not cfg.agent_v2.llm_numeric_routing) else client
                plan=self.optimizer.run(problem,cfg.forecast.service_quantile,spec['mode'],route_client,free)
                plan_ref=record('propose',plan,[problem_ref])
                if spec['critic'] or cfg.agent_v2.enabled:
                    critic_client=None if single or (cfg.agent_v2.enabled and not cfg.agent_v2.llm_critic) else client
                    verdict=RiskCriticAgent().run(plan,problem,documents,critic_client,free,screen=cfg.gate.injection_screen)
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
                        plan=self.optimizer.run(problem,cfg.forecast.service_quantile,spec['mode'])
                        record('propose',plan,[problem_ref])
                        verdict=RiskCriticAgent().run(plan,problem,documents,screen=cfg.gate.injection_screen)
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
               'effective_policy':self.policy+('-v2-hybrid' if cfg.agent_v2.enabled and self.client else '-v2-parser' if cfg.agent_v2.enabled else '')+('-fallback' if used_fallback else '')+('-forecast-override' if cfg.forecast_override else ''),
               'day':snapshot.lineage.day,'lineage':snap.lineage.model_dump(),'references':refs,'stages':stages,
               'consumed_refs':sorted(set(consumed)),'plan_action_hash':plan.action_hash(),'autonomy':autonomy.model_dump(),
               'fallback':used_fallback,'errors':fallback_reasons,'model_name':self.model.name,
               'llm':{'calls':self.client.calls-call_start if self.client else 0,
                      'tokens':self.client.tokens-token_start if self.client else 0,
                      'errors':self.client.errors-error_start if self.client else 0,
                      'artifacts':self.client.refs[ref_start:] if self.client else []},
               'execution':None,'outcome':None}
        if cfg.agent_v2.enabled:
            trace['agent_version']='v2'
            trace['agent_v2_config']=cfg.agent_v2.model_dump()
            trace['recovery']=recovery_report
        return Decision(decision_id,plan,autonomy,trace,cert,problem)
