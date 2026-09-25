"""Per-decision autonomy is a policy over evidence, never an LLM self-assessment."""
from __future__ import annotations
import numpy as np
from .schemas import Autonomy
from .optimization import policy_plan

def decide_autonomy(certificate,plan,problem,forecast,constraints,gate,hold_count=0,enabled=True):
    if not enabled:
        permitted=gate.fixed_level in {'bounded','full'}
        return Autonomy(level=gate.fixed_level,permitted=permitted,reasons=['Fixed-autonomy ablation in simulator'],
                        inputs={'quality_logged_but_not_gated':certificate.quality},required_approvals=0 if permitted else 1)
    hard=certificate.hard_fail
    inputs={'quality':certificate.quality,'constraint_confidence':constraints.confidence if constraints else 0,
            'policy_version':gate.version,'hold_count':hold_count}
    if hard or problem is None or plan is None:
        return Autonomy(level='advisory',permitted=False,reasons=['State hard failure or incomplete verified tools'],inputs=inputs,urgent=hold_count>=gate.hold_budget)
    reasons=[];q=certificate.quality
    if q<gate.min_quality:reasons.append('Evidence quality below autonomous threshold')
    if constraints.issues or constraints.confidence<gate.min_confidence:reasons.append('Constraints unresolved or low-confidence')
    if plan.method=='stochastic_milp' and not plan.solver.get('feasible'):reasons.append('No verified solver incumbent')
    idx={s['series_id']:i for i,s in enumerate(problem['series'])};orders=np.zeros(len(idx))
    for o in plan.orders:
        if o.series_id in idx:orders[idx[o.series_id]]+=o.quantity
    baseline=policy_plan(problem)
    base=np.zeros(len(idx))
    for o in baseline.orders:base[idx[o.series_id]]+=o.quantity
    spend=float(sum(o.quantity*problem['parameters']['unit_cost'][idx[o.series_id]] for o in plan.orders))
    spend+=sum(t.quantity*problem['config']['transfer_cost'] for t in plan.transfers)
    spend+=sum(problem['supplier_parameters'][s]['fixed_cost'] for s in {o.supplier for o in plan.orders if o.quantity>0})
    deviation=float(np.abs(orders-base).sum()/max(1,base.sum()))
    samples=np.asarray(forecast.samples);mean=samples.mean(axis=(0,2))
    ip=np.asarray(problem['on_hand'])+np.asarray(problem['receipts']).sum(axis=2).mean(axis=0)+orders
    active=orders>0
    days_supply=float(np.max(ip[active]/np.maximum(mean[active],0.1))) if active.any() else 0.
    totals=samples.sum(axis=(1,2));dispersion=float(totals.std()/max(totals.mean(),1))
    inputs.update(spend=spend,baseline_deviation=deviation,max_days_supply=days_supply,forecast_dispersion=dispersion)
    if spend>gate.max_spend:reasons.append('Spend exceeds autonomous cap')
    if deviation>gate.max_deviation:reasons.append('Deviation from deterministic baseline exceeds cap')
    if days_supply>gate.max_days_supply:reasons.append('Projected days of supply exceed cap')
    if dispersion>gate.max_dispersion:reasons.append('Forecast dispersion exceeds cap')
    approvals=2 if spend>gate.two_person_spend else 1
    if reasons:return Autonomy(level='approval',permitted=False,reasons=reasons,inputs=inputs,urgent=hold_count>=gate.hold_budget,required_approvals=approvals)
    level='full' if q>=gate.full_quality and spend<=gate.max_spend/2 else 'bounded'
    return Autonomy(level=level,permitted=True,reasons=['Verified evidence and risk inside simulator policy limits'],inputs=inputs)
