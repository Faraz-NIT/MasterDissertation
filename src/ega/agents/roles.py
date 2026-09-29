"""Seven bounded roles. Tools compute quantities; models interpret source evidence."""
from __future__ import annotations
from .llm import Extraction,Triage,Route,Review,SingleOutput
from ..schemas import ConstraintSet, Verdict, Check, Receipt
from ..quality import certify
from ..constraints import extract_templates,verify_constraints,screen_injection
from ..optimization import solve,policy_plan,check_plan

class StateReconciliationAgent:
    def run(self,snapshot,gate,client=None,memory=None,free_form=False):
        certificate=certify(snapshot,gate)
        anomalies=[c.model_dump() for c in certificate.checks if c.outcome!='pass']
        if client and anomalies:
            response=client.ask('state reconciliation agent',{'anomalies':anomalies,'stage_days':snapshot.stage_days,
                        'notes':snapshot.operator_notes,'source_locations':snapshot.source_locations,
                        'loaded_locations':snapshot.loaded_locations,'approved_memory':memory or [],
                        'allowed_evidence_refs':[c['name'] for c in anomalies]},Triage,free_form)
            allowed={c['name'] for c in anomalies}
            certificate.hypotheses=[h.model_dump() for h in response.hypotheses if set(h.evidence_refs)<=allowed]
        # A hypothesis cannot touch quality, checks, or state, including through memory.
        return certificate

class DemandForecastAgent:
    def __init__(self,model):self.model=model
    def run(self,snapshot,solver,seed):return self.model.predict(snapshot,solver.horizon,solver.scenarios,seed)

class SupplierConstraintAgent:
    def run(self,snapshot,documents,gate,client=None,free_form=False,single=False,certificate=None):
        if client is None:raw=extract_templates(documents,snapshot.lineage)
        else:
            values=[];issues=[]
            for start in range(0,len(documents),6):
                docs=documents[start:start+6]
                flagged=[d.ref for d in docs if not d.authenticated or screen_injection(d.text)]
                if flagged:
                    issues.extend(f'untrusted/injected source {ref}' for ref in flagged)
                    docs=[d for d in docs if d.ref not in flagged]
                if not docs:continue
                payload={'documents':[d.payload() for d in docs],'day':snapshot.lineage.day,
                         'known_entities':[s.model_dump() for s in snapshot.series],
                         'task':'Extract all active source rules. Preserve values and units exactly. Do not silently resolve conflicts.',
                         'format_conventions':FORMAT_CONVENTIONS}
                if single:
                    payload['state_certificate']=certificate.model_dump() if certificate else None
                    # Same routing instruction the multi-agent optimizer receives, so B6 differs only in structure.
                    payload['allowed_tools']=['stochastic_milp']
                    payload['task']+=' Also route the numeric decision: set requested_tool to stochastic_milp.'
                    response=client.ask('single generalist agent (all roles)',payload,SingleOutput)
                    if response.requested_tool not in {'stochastic_milp','milp'}:
                        issues.append('Single agent requested a tool outside its allowlist')
                else:
                    response=client.ask('supplier and constraint agent',payload,Extraction,free_form)
                values.extend(response.constraints);issues.extend(response.issues)
            raw=ConstraintSet(lineage=snapshot.lineage,constraints=values,issues=issues)
        return verify_constraints(raw,snapshot.series,documents,snapshot.lineage.day,gate.min_confidence)

FORMAT_CONVENTIONS=('In source rules, conversion=none means no unit conversion applies: return conversion as null. '
                    'This is the documented encoding, not an ambiguity or an issue.')

class OptimizationAgent:
    def run(self,problem,service_quantile=0.95,mode='milp',client=None,free_form=False):
        # A model may request a simpler tool, but may not turn a coupled formulation into an uncoupled policy.
        if client:
            route=client.ask('replenishment optimization agent',{'budget':problem['budget'],
                 'suppliers':problem['supplier_parameters'],'edges':len(problem['edges']),
                 'allowed_tools':['stochastic_milp'],'task':('Route this verified coupled specification; request stochastic_milp. Set escalation_reason to an '
                         'empty string unless the specification needs human review; any non-empty value escalates.')},Route,free_form)
            if route.requested_tool not in {'stochastic_milp','milp'}:
                raise ValueError('Model requested a tool outside the optimizer allowlist')
            if route.escalation_reason:raise ValueError('Optimizer requested escalation: '+route.escalation_reason)
        return solve(problem) if mode=='milp' else policy_plan(problem,service_quantile,ss=mode=='ss')

class RiskCriticAgent:
    def run(self,plan,problem,documents,client=None,free_form=False):
        failures=check_plan(plan,problem);checks=[]
        if plan.method=='stochastic_milp' and not plan.solver.get('feasible'):failures.append('missing_solver_feasibility')
        for doc in documents:
            if screen_injection(doc.text):failures.append('injection_screening')
        checks.append(Check(name='independent_action_feasibility',family='constraint',outcome='hard_fail' if failures else 'pass',evidence={'failures':sorted(set(failures))}))
        # Capacity/budget stress verifies robustness; failing a hypothetical stress is not a current hard violation.
        for label,factor in [('budget_80pct',0.8),('capacity_80pct',0.8)]:
            import copy
            stress=copy.deepcopy(problem)
            if label.startswith('budget'):stress['budget']*=factor
            else:
                for p in stress['supplier_parameters'].values():p['capacity']*=factor
            stress_fails=check_plan(plan,stress)
            checks.append(Check(name=label,family='stress',outcome='warn' if stress_fails else 'pass',evidence={'failures':stress_fails},weight=0))
        decision='veto' if failures else 'pass'
        if client:
            review=client.ask('risk and critic agent',{'action':plan.model_dump(),'independent_checks':[c.model_dump() for c in checks],
                    'allowed_evidence_refs':[c.name for c in checks],'task':'Do not modify the proposal. Return pass, veto, or escalate with cited concerns.'},Review,free_form)
            if not set(review.evidence_refs)<={c.name for c in checks}:decision='escalate'
            elif review.verdict in {'veto','escalate'} and decision!='veto':decision=review.verdict
            elif review.verdict!='pass' and decision=='pass':decision='escalate'
            checks.append(Check(name='semantic_review',family='semantic',outcome='warn' if review.concerns else 'pass',evidence=review.model_dump()))
        return Verdict(lineage=plan.lineage,decision=decision,checks=checks)

class ExecutionMonitoringAgent:
    def __init__(self,store):self.store=store
    def run(self,decision_id,plan,autonomy,environment,true_problem,approvals=None):
        # The only execution adapter is an in-process simulator. No ERP endpoint exists.
        if not autonomy.permitted:
            receipt=Receipt(decision_id=decision_id,idempotency_key=decision_id,action_hash=plan.action_hash(),status='held',order_ids=[])
        else:
            if autonomy.required_approvals>len(set(approvals or [])):
                raise ValueError('Insufficient distinct reviewer approvals')
            existing=self.store.db.execute('SELECT action_hash,payload FROM receipts WHERE idempotency_key=?',(decision_id,)).fetchone()
            if existing:
                if existing[0]!=plan.action_hash():raise ValueError('Duplicate decision key with a different action')
                import json
                return Receipt.model_validate(json.loads(existing[1])),{'duplicate':True,'purchase':0.,'fixed_order':0.,'transfer':0.}
            ids,costs=environment.execute(plan,true_problem,decision_id)
            receipt=Receipt(decision_id=decision_id,idempotency_key=decision_id,action_hash=plan.action_hash(),status='executed',order_ids=ids)
            self.store.record_receipt(receipt)
            return receipt,costs
        self.store.record_receipt(receipt)
        return receipt,{'purchase':0.,'fixed_order':0.,'transfer':0.}
