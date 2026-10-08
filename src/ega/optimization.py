"""Two-stage, receding-horizon stochastic MILP with exact lost-sales dynamics.

Only today's purchases/transfers are first-stage decisions. Scenario-specific inventory
and lost-sales variables are recourse. Re-solve tomorrow; no hidden future purchases.
"""
from __future__ import annotations
import time
from collections import defaultdict
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix
from .config import SolverConfig
from .schemas import Snapshot, Forecast, ConstraintSet, Plan, Order, Transfer, Lineage, Series, assert_lineage
from .constraints import lookup
from .util import keyed_rng,digest

def arrival_opportunity(snapshot: Snapshot, order) -> str:
    """Remove only this simulator run's namespace; preserve the business order suffix."""
    prefix=snapshot.lineage.run_id+':'
    return order.order_id[len(prefix):] if order.order_id.startswith(prefix) else order.order_id

def build_problem(snapshot: Snapshot, forecast: Forecast, constraints: ConstraintSet,
                  config: SolverConfig, seed: int) -> dict:
    assert_lineage(snapshot,forecast,constraints)
    if constraints.issues:raise ValueError('Unverified constraints: '+'; '.join(constraints.issues))
    series=snapshot.series;n=len(series);W=config.scenarios;T=config.horizon
    demand=np.asarray(forecast.samples,dtype=float)
    if demand.shape!=(W,n,T):raise ValueError('Forecast dimensions do not match solver configuration')
    params={p:[lookup(constraints,s,p,0 if p=='moq' else None) for s in series]
            for p in ['pack','moq','unit_cost','lead_time','eligibility']}
    suppliers=sorted({s.supplier for s in series});sparams={}
    for sup in suppliers:
        rows=[c for c in constraints.constraints if c.entity==sup]
        find=lambda p,default:next((c.value for c in rows if c.parameter==p),default)
        agg=next((c for c in rows if c.parameter=='aggregate_moq'),None)
        sparams[sup]={'capacity':find('capacity',config.max_order_units*n),
                      'fixed_cost':find('fixed_cost',0),'aggregate_moq':find('aggregate_moq',0),
                      'aggregate_unit':agg.unit if agg else 'unit'}
    conversion=[]
    for s in series:
        conversion.append(lookup(constraints,s,'conversion',1) if sparams[s.supplier]['aggregate_unit']=='m' else 1)
    lead=np.zeros((W,n),dtype=int);receipts=np.zeros((W,n,T));assumptions=[]
    index={s.series_id:i for i,s in enumerate(series)}
    for w in range(W):
        for i,s in enumerate(series):
            rng=keyed_rng(seed,'predicted_lead',snapshot.lineage.day,s.series_id,w)
            lead[w,i]=max(1,int(params['lead_time'][i])+int(rng.choice([-1,0,1],p=[0.15,0.7,0.15])))
        for po in snapshot.open_orders:
            if po.series_id not in index or not po.stock_line:continue
            i=index[po.series_id]
            if po.due_day is None:
                opportunity=arrival_opportunity(snapshot,po) if config.unknown_arrival_rng=='v2_opportunity' else po.order_id
                rng=keyed_rng(seed,'unknown_po_arrival',snapshot.lineage.day,opportunity,w)
                # Conditional arrival AFTER today when overdue/unknown; never infer receipt into the past.
                base=(po.ordered_day if po.ordered_day is not None else snapshot.lineage.day)+int(params['lead_time'][i])
                offset=max(1,base-snapshot.lineage.day)+int(rng.integers(0,3))
            else:offset=max(0,po.due_day-snapshot.lineage.day)
            if offset<T:receipts[w,i,offset]+=max(0,po.quantity)
    for po in snapshot.open_orders:
        if po.due_day is None:
            assumptions.append({'source':'system_default','parameter':'arrival_offset','order_id':po.order_id,
                                'rule':'max(1, order_day + lead - decision_day) + discrete_uniform(0,2)',
                                'confidence':0.6})
            if config.unknown_arrival_rng=='v2_opportunity':
                assumptions[-1].update(sampling_key=arrival_opportunity(snapshot,po),
                                       rng_version='v2_opportunity')
    edges=[]
    if config.allow_transfers:
        for i,s in enumerate(series):
            for j,d in enumerate(series):
                if i!=j and s.item_id==d.item_id and s.cluster==d.cluster and params['eligibility'][j]:edges.append((i,j))
    return {'lineage':snapshot.lineage.model_dump(),'series':[s.model_dump() for s in series],
            'on_hand':snapshot.observed_quantities(),'demand':demand.tolist(),'receipts':receipts.tolist(),
            'leads':lead.tolist(),'parameters':params,'supplier_parameters':sparams,'conversion':conversion,
            'budget':lookup(constraints,None,'budget',config.budget),'edges':edges,
            'constraints':[c.model_dump() for c in constraints.constraints],'assumptions':assumptions,
            'config':config.model_dump(),'forecast_ref':digest(forecast),'snapshot_ref':digest(snapshot)}

class MatrixBuilder:
    def __init__(self):self.cost=[];self.lower=[];self.upper=[];self.integrality=[];self.rows=[];self.lo=[];self.hi=[];self.names=[]
    def var(self,cost=0.,lo=0.,hi=np.inf,integer=False):
        i=len(self.cost);self.cost.append(cost);self.lower.append(lo);self.upper.append(hi);self.integrality.append(int(integer));return i
    def row(self,terms,lo=-np.inf,hi=np.inf,name=''):
        cleaned={k:float(v) for k,v in terms.items() if v!=0};self.rows.append(cleaned);self.lo.append(lo);self.hi.append(hi);self.names.append(name)
    def matrix(self):
        rr=[];cc=[];vv=[]
        for r,terms in enumerate(self.rows):
            for col,v in terms.items():rr.append(r);cc.append(col);vv.append(v)
        return coo_matrix((vv,(rr,cc)),shape=(len(self.rows),len(self.cost))).tocsc()

def empty_plan(problem:dict,method:str='hold',diagnostics=None) -> Plan:
    return Plan(lineage=Lineage.model_validate(problem['lineage']),method=method,orders=[],transfers=[],objective=None,
                components={},solver={'status':'not_solved','feasible':False},active_constraints=[],diagnostics=diagnostics or [])

def solve(problem:dict) -> Plan:
    start=time.perf_counter();cfg=SolverConfig.model_validate(problem['config'])
    series=[Series.model_validate(s) for s in problem['series']];n=len(series)
    D=np.asarray(problem['demand']);R=np.asarray(problem['receipts']);L=np.asarray(problem['leads']);H0=np.asarray(problem['on_hand'])
    W,_,T=D.shape;p=problem['parameters'];packs=np.asarray(p['pack']);costs=np.asarray(p['unit_cost']);conv=np.asarray(problem['conversion'])
    if np.any(H0<0):return empty_plan(problem,'milp',['Negative observed on-hand; formulation rejected'])
    b=MatrixBuilder();lam=cfg.risk_weight;alpha=cfg.cvar_alpha
    suppliers=list(problem['supplier_parameters']);supplier_vars={s:b.var(cost=(1+lam)*problem['supplier_parameters'][s]['fixed_cost'],hi=1,integer=True) for s in suppliers}
    k=[];z=[];first_cost={supplier_vars[s]:problem['supplier_parameters'][s]['fixed_cost'] for s in suppliers}
    for i,s in enumerate(series):
        maxpacks=int(cfg.max_order_units//packs[i]) if p['eligibility'][i] else 0
        k.append(b.var(cost=(1+lam)*costs[i]*packs[i],hi=maxpacks,integer=True));z.append(b.var(hi=1,integer=True))
        first_cost[k[i]]=costs[i]*packs[i]
        b.row({k[i]:packs[i],z[i]:-p['moq'][i]},lo=0,name=f'moq:{i}')
        b.row({k[i]:packs[i],z[i]:-cfg.max_order_units},hi=0,name=f'line_activation:{i}')
        b.row({k[i]:packs[i],supplier_vars[s.supplier]:-cfg.max_order_units},hi=0,name=f'supplier_activation:{i}')
    transfers=[]
    for i,j in problem['edges']:
        v=b.var(cost=(1+lam)*cfg.transfer_cost,hi=max(0,H0[i]),integer=True)
        transfers.append((i,j,v));first_cost[v]=cfg.transfer_cost
    for i in range(n):b.row({v:1 for src,dst,v in transfers if src==i},hi=H0[i],name=f'transfer_availability:{i}')
    for s in suppliers:
        inds=[i for i,x in enumerate(series) if x.supplier==s];sp=problem['supplier_parameters'][s]
        b.row({k[i]:packs[i] for i in inds},hi=sp['capacity'],name=f'capacity:{s}')
        b.row({**{k[i]:packs[i]*conv[i] for i in inds},supplier_vars[s]:-sp['aggregate_moq']},lo=0,name=f'aggregate_moq:{s}')
    b.row(first_cost,hi=problem['budget'],name='budget')
    holds=np.empty((W,n,T),dtype=int);shorts=np.empty_like(holds);recourse=[]
    for w in range(W):
        wc={}
        for i in range(n):
            max_stock=float(H0[i]+R[w,i].sum()+cfg.max_order_units+sum(H0[src] for src,dst,_ in transfers if dst==i)+1)
            for t in range(T):
                h=b.var(cost=costs[i]*cfg.holding_rate/W,hi=max_stock)
                u=b.var(cost=costs[i]*cfg.shortage_multiplier/W,hi=float(D[w,i,t]))
                mode=b.var(hi=1,integer=True)
                holds[w,i,t]=h;shorts[w,i,t]=u
                wc[h]=costs[i]*cfg.holding_rate;wc[u]=costs[i]*cfg.shortage_multiplier
                # Exact complementarity: no deliberate lost sale while stock remains.
                b.row({h:1,mode:-max_stock},hi=0,name=f'physical_stock:{w}:{i}:{t}')
                b.row({u:1,mode:float(D[w,i,t])},hi=float(D[w,i,t]),name=f'physical_sale:{w}:{i}:{t}')
                terms={h:1,u:-1}
                if t>0:terms[int(holds[w,i,t-1])]=-1
                if t==L[w,i]:terms[k[i]]=-packs[i]
                for src,dst,v in transfers:
                    if src==i and t==0:terms[v]=terms.get(v,0)+1
                    if dst==i and t==cfg.transfer_lead:terms[v]=terms.get(v,0)-1
                rhs=float(R[w,i,t]-D[w,i,t]+(H0[i] if t==0 else 0))
                b.row(terms,lo=rhs,hi=rhs,name=f'balance:{w}:{i}:{t}')
        for loc in sorted({s.location for s in series}):
            inds=[i for i,s in enumerate(series) if s.location==loc]
            for t in range(T):b.row({int(holds[w,i,t]):1 for i in inds},hi=cfg.storage_per_location,name=f'storage:{w}:{loc}:{t}')
        recourse.append(wc)
    eta=b.var(cost=lam)
    for w in range(W):
        excess=b.var(cost=lam/((1-alpha)*W))
        terms={eta:1,excess:1}
        for v,c in first_cost.items():terms[v]=terms.get(v,0)-c
        for v,c in recourse[w].items():terms[v]=terms.get(v,0)-c
        b.row(terms,lo=0,name=f'cvar:{w}')
    A=b.matrix()
    try:
        result=milp(np.asarray(b.cost),integrality=np.asarray(b.integrality),
                    bounds=Bounds(b.lower,b.upper),constraints=LinearConstraint(A,b.lo,b.hi),
                    options={'time_limit':cfg.time_limit,'mip_rel_gap':cfg.mip_gap,'presolve':True})
    except (ValueError,RuntimeError) as exc:return empty_plan(problem,'milp',[f'Solver failed: {exc}'])
    if result.x is None:
        plan=empty_plan(problem,'milp',[str(result.message),'No feasible incumbent; no contract is silently relaxed.'])
        plan.solver={'status':int(result.status),'feasible':False,'seconds':time.perf_counter()-start,
                     'diagnostic':'HiGHS via SciPy does not expose IIS here; solver status is not an IIS certificate.'}
        return plan
    x=result.x;ax=A@x
    primal_error=max(float(np.max(np.maximum(np.asarray(b.lo)-ax,0))),float(np.max(np.maximum(ax-np.asarray(b.hi),0))),
                     float(np.max(np.maximum(np.asarray(b.lower)-x,0))),float(np.max(np.maximum(x-np.asarray(b.upper),0))))
    integer_indices=np.flatnonzero(b.integrality);integer_error=float(np.max(np.abs(x[integer_indices]-np.rint(x[integer_indices]))))
    feasible=primal_error<1e-5 and integer_error<1e-5
    if not feasible:return empty_plan(problem,'milp',[f'Independent numerical residual failure: primal={primal_error}, integer={integer_error}'])
    orders=[Order(series_id=series[i].series_id,supplier=series[i].supplier,quantity=int(round(x[k[i]]))*int(packs[i])) for i in range(n) if x[k[i]]>0.5]
    moves=[Transfer(item_id=series[i].item_id,source_series=series[i].series_id,destination_series=series[j].series_id,quantity=int(round(x[v]))) for i,j,v in transfers if x[v]>0.5]
    first=sum(c*x[v] for v,c in first_cost.items());scenario_cost=np.array([first+sum(c*x[v] for v,c in wc.items()) for wc in recourse])
    purchase=sum(costs[i]*packs[i]*round(x[k[i]]) for i in range(n));transfer=sum(cfg.transfer_cost*round(x[v]) for _,_,v in transfers)
    fixed=sum(problem['supplier_parameters'][s]['fixed_cost']*round(x[supplier_vars[s]]) for s in suppliers)
    holding=sum(float(x[holds[w,i,t]])*costs[i]*cfg.holding_rate/W for w in range(W) for i in range(n) for t in range(T))
    shortage=sum(float(x[shorts[w,i,t]])*costs[i]*cfg.shortage_multiplier/W for w in range(W) for i in range(n) for t in range(T))
    # Exact empirical CVaR with fractional mass at the quantile boundary.
    from .evaluation.metrics import cvar
    cv=cvar(scenario_cost,alpha)
    active=[b.names[i] for i in range(len(ax)) if (np.isfinite(b.hi[i]) and abs(ax[i]-b.hi[i])<1e-5) or (np.isfinite(b.lo[i]) and abs(ax[i]-b.lo[i])<1e-5)]
    obj=float(scenario_cost.mean()+lam*cv)
    return Plan(lineage=Lineage.model_validate(problem['lineage']),method='stochastic_milp',orders=orders,transfers=moves,
                objective=obj,components={'purchase':float(purchase),'fixed_order':float(fixed),'transfer':float(transfer),
                                         'holding':float(holding),'shortage':float(shortage),'cvar':float(cv),'expected_cost':float(scenario_cost.mean())},
                solver={'status':int(result.status),'message':str(result.message),'feasible':feasible,'optimal':result.status==0,
                        'gap':float(result.mip_gap) if result.mip_gap is not None and np.isfinite(result.mip_gap) else None,
                        'dual_bound':float(result.mip_dual_bound) if result.mip_dual_bound is not None and np.isfinite(result.mip_dual_bound) else None,
                        'raw_objective':float(result.fun),'max_primal_violation':primal_error,'max_integer_violation':integer_error,
                        'variables':len(x),'rows':len(ax),'seconds':time.perf_counter()-start,'problem_hash':digest(problem)},
                active_constraints=active)

def policy_plan(problem:dict,service_quantile:float=0.95,ss:bool=False) -> Plan:
    """Transparent line-level order-up-to/(s,S); deliberately does not repair coupled constraints."""
    D=np.asarray(problem['demand']);R=np.asarray(problem['receipts']);p=problem['parameters'];orders=[]
    for i,s in enumerate(problem['series']):
        if not p['eligibility'][i]:continue
        horizon=min(D.shape[2],int(p['lead_time'][i])+1)
        target=float(np.quantile(D[:,i,:horizon].sum(axis=1),service_quantile))
        ip=problem['on_hand'][i]+float(np.mean(R[:,i,:].sum(axis=1)))
        trigger=float(np.quantile(D[:,i,:max(1,horizon-1)].sum(axis=1),0.5))
        q=max(0,target-ip) if (not ss or ip<trigger) else 0
        if q>0:q=max(p['moq'][i],np.ceil(q/p['pack'][i])*p['pack'][i])
        if q>0:orders.append(Order(series_id=s['series_id'],supplier=s['supplier'],quantity=int(q)))
    return Plan(lineage=Lineage.model_validate(problem['lineage']),method='s_S' if ss else 'order_up_to',orders=orders,
                transfers=[],objective=None,components={},solver={'status':'policy','feasible':None},active_constraints=[])

def check_plan(plan:Plan,problem:dict) -> list[str]:
    """Independent action-level verifier, separate from the MILP's constraint construction."""
    failures=[];series=[Series.model_validate(s) for s in problem['series']];idx={s.series_id:i for i,s in enumerate(series)}
    p=problem['parameters'];q=np.zeros(len(series));out=np.zeros(len(series));sup_totals=defaultdict(float);spend=0.
    if plan.lineage != Lineage.model_validate(problem['lineage']):failures.append('lineage_mismatch')
    seen=set()
    for order in plan.orders:
        if order.series_id not in idx:failures.append('unknown_item_location');continue
        i=idx[order.series_id];s=series[i]
        if order.series_id in seen:failures.append('duplicate_order_line')
        seen.add(order.series_id);q[i]+=order.quantity
        if order.supplier!=s.supplier:failures.append('wrong_supplier')
        if order.quantity%int(p['pack'][i]):failures.append('pack_integrality')
        if 0<order.quantity<p['moq'][i]:failures.append('line_moq')
        if order.quantity>0 and not p['eligibility'][i]:failures.append('eligibility')
        if order.quantity>problem['config']['max_order_units']:failures.append('max_order')
        sup_totals[s.supplier]+=order.quantity;spend+=order.quantity*p['unit_cost'][i]
    for move in plan.transfers:
        if move.source_series not in idx or move.destination_series not in idx:failures.append('unknown_transfer_endpoint');continue
        i=idx[move.source_series];j=idx[move.destination_series]
        if i==j or series[i].item_id!=series[j].item_id or series[i].cluster!=series[j].cluster or move.item_id!=series[i].item_id:failures.append('transfer_graph')
        if not p['eligibility'][j]:failures.append('transfer_eligibility')
        if [i,j] not in [list(e) for e in problem['edges']]:failures.append('transfer_not_allowed')
        out[i]+=move.quantity;spend+=move.quantity*problem['config']['transfer_cost']
    if np.any(out>np.asarray(problem['on_hand'])+1e-8):failures.append('transfer_availability')
    for sup,total in sup_totals.items():
        limits=problem['supplier_parameters'][sup]
        if total>limits['capacity']+1e-6:failures.append('supplier_capacity')
        consumption=sum(q[i]*problem['conversion'][i] for i,s in enumerate(series) if s.supplier==sup)
        if total>0 and consumption+1e-6<limits['aggregate_moq']:failures.append('aggregate_moq')
        if total>0:spend+=limits['fixed_cost']
    if spend>problem['budget']+1e-6:failures.append('budget')
    return sorted(set(failures))
