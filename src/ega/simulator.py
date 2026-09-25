"""Closed-loop lost-sales simulator. Agents never receive this object's true state."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .schemas import Snapshot,Lineage,InventoryRow,PurchaseOrder,SalesLine
from .util import keyed_rng,digest

@dataclass
class Shipment:
    order_id:str
    series_id:str
    supplier:str
    quantity:float
    ordered_day:int
    true_due_day:int
    missing_eta:bool
    kind:str='supplier'

class InventoryEnvironment:
    def __init__(self,panel,first_day,seed,run_id,config):
        self.panel=panel;self.seed=seed;self.run_id=run_id;self.config=config;self.day=first_day
        self.index={s.series_id:i for i,s in enumerate(panel.series)}
        hist=np.asarray(panel.sales[:,max(0,first_day-56):first_day]);mu=hist.mean(axis=1);sd=hist.std(axis=1)
        self.on_hand=np.ceil(mu*5+1.65*sd*np.sqrt(5)).astype(float)
        # Independent source movement ledger, not a hidden oracle API: exposed explicitly in snapshots.
        # This redundant source is an optimistic simulation assumption documented in the methodology.
        self.ledger=self.on_hand.copy();self.previous_start=self.on_hand.copy()
        self.sales_history=[list(row) for row in np.asarray(panel.sales[:,:first_day])]
        self.flags=[[False]*first_day for _ in panel.series];self.pending=[];self.executed=set()
        self.last_sales=np.zeros(panel.n);self.last_transfers=np.zeros(panel.n);self.received=np.zeros(panel.n)
        self.received_ids=[]
        for i,s in enumerate(panel.series):
            qty=float(np.ceil(mu[i]*2))
            if qty:
                due=first_day+int(keyed_rng(seed,'initial_pipeline',s.series_id).integers(1,4))
                self.pending.append(Shipment(f'initial:{s.series_id}',s.series_id,s.supplier,qty,first_day-1,due,False))
    def begin_day(self,day):
        self.day=day;self.received=np.zeros(self.panel.n);self.received_ids=[];remaining=[]
        for order in self.pending:
            if order.true_due_day<=day:
                i=self.index[order.series_id];self.on_hand[i]+=order.quantity;self.ledger[i]+=order.quantity
                self.received[i]+=order.quantity;self.received_ids.append(order.order_id)
            else:remaining.append(order)
        self.pending=remaining
    def snapshot(self,lookback,reveal_arrivals=False):
        day=self.day;series=[s.model_copy(deep=True) for s in self.panel.series]
        prices=self.panel.price_at(day);safe_prices=np.where(np.isfinite(prices),prices,0).tolist()
        history=[row[max(0,day-lookback):day] for row in self.sales_history]
        flags=[row[max(0,day-lookback):day] for row in self.flags]
        lines=[]
        for i,s in enumerate(series):
            qty=float(history[i][-1]) if history[i] else 0.;price=float(safe_prices[i])
            lines.append(SalesLine(key=f'{s.series_id}:{day-1}',quantity=qty,unit_price=price,line_total=qty*price,currency='USD',series_id=s.series_id))
        inventory=[InventoryRow(series_id=s.series_id,quantity=float(self.on_hand[i])) for i,s in enumerate(series)]
        version=digest({'run':self.run_id,'day':day,'inventory':inventory,'orders':[(p.order_id,p.quantity) for p in self.pending]})
        return Snapshot(lineage=Lineage(snapshot_version=version,run_id=self.run_id,day=day),series=series,inventory=inventory,
            open_orders=[PurchaseOrder(order_id=p.order_id,series_id=p.series_id,supplier=p.supplier,quantity=p.quantity,ordered_day=p.ordered_day,
                                       due_day=None if p.missing_eta and not reveal_arrivals else p.true_due_day,source=p.kind) for p in self.pending],
            history=history,history_days=list(range(max(0,day-lookback),day)),stockout_flags=flags,prices=safe_prices,sales_lines=lines,
            stage_days={k:day for k in ['inventory','sales','products','prices','open_orders']},
            source_locations=sorted({s.location for s in series}),loaded_locations=sorted({s.location for s in series}),source_row_count=len(series),
            expected_inventory={s.series_id:float(self.ledger[i]) for i,s in enumerate(series)},
            previous_inventory={s.series_id:float(self.previous_start[i]) for i,s in enumerate(series)},
            previous_inventory_hash=digest(sorted([(s.series_id,float(self.previous_start[i])) for i,s in enumerate(series)])),
            movement_volume=float(self.last_sales.sum()+self.received.sum()+np.abs(self.last_transfers).sum()))
    def execute(self,plan,problem,decision_id):
        if decision_id in self.executed:raise ValueError('Duplicate execution inside simulator')
        self.executed.add(decision_id);p=problem['parameters'];ids=[];costs={'purchase':0.,'fixed_order':0.,'transfer':0.}
        capacity={s:v['capacity'] for s,v in problem['supplier_parameters'].items()};used=set();self.last_transfers=np.zeros(self.panel.n)
        # Transfer commitments and physical shipments are both recorded; insufficient physical stock is not manufactured.
        for j,move in enumerate(plan.transfers):
            if move.source_series not in self.index or move.destination_series not in self.index:continue
            i=self.index[move.source_series];target=self.index[move.destination_series]
            quantity=min(float(move.quantity),max(0,self.on_hand[i]))
            self.on_hand[i]-=quantity;self.ledger[i]-=quantity;self.last_transfers[i]-=quantity
            oid=f'{decision_id}:transfer:{j}';ids.append(oid)
            self.pending.append(Shipment(oid,move.destination_series,self.panel.series[target].supplier,quantity,self.day,self.day+self.config.solver.transfer_lead,False,'transfer'))
            costs['transfer']+=quantity*self.config.solver.transfer_cost
        for order in sorted(plan.orders,key=lambda x:x.series_id):
            if order.series_id not in self.index:continue
            i=self.index[order.series_id];true_supplier=self.panel.series[i].supplier
            rng=keyed_rng(self.seed,'realized_supply',self.day,order.series_id)
            available=capacity.get(true_supplier,0)
            quantity=min(float(order.quantity),available)
            # Exogenous supplier fulfillment draws keyed by action opportunity, not action count.
            cancelled=rng.random()<0.02
            fill=float(rng.choice([0.8,1.0],p=[0.1,0.9]))
            quantity=0.0 if cancelled else float(np.floor(quantity*fill))
            capacity[true_supplier]=max(0,available-quantity)
            lead=max(1,int(p['lead_time'][i])+int(rng.choice([-1,0,1],p=[0.15,0.7,0.15])))
            if rng.random()<0.05:lead+=2
            missing=bool(rng.random()<0.1)
            oid=f'{decision_id}:po:{order.series_id}';ids.append(oid)
            if quantity>0:self.pending.append(Shipment(oid,order.series_id,true_supplier,quantity,self.day,self.day+lead,missing))
            costs['purchase']+=quantity*p['unit_cost'][i];used.add(true_supplier)
        costs['fixed_order']=sum(problem['supplier_parameters'][s]['fixed_cost'] for s in used)
        return ids,costs
    def end_day(self,demand,unit_costs):
        start=self.on_hand.copy();sold=np.minimum(np.maximum(self.on_hand,0),demand);lost=demand-sold
        self.on_hand-=sold;self.ledger-=sold;self.last_sales=sold.copy()
        overflow=np.zeros(self.panel.n)
        for loc in {s.location for s in self.panel.series}:
            inds=[i for i,s in enumerate(self.panel.series) if s.location==loc]
            total=float(self.on_hand[inds].sum());cap=self.config.solver.storage_per_location
            if total>cap:
                overflow[inds]=self.on_hand[inds]*(total-cap)/total
                self.on_hand[inds]-=overflow[inds];self.ledger[inds]-=overflow[inds]
        for i in range(self.panel.n):self.sales_history[i].append(float(sold[i]));self.flags[i].append(bool(lost[i]>0))
        costs=np.asarray(unit_costs)
        result={'demand':float(demand.sum()),'sales':float(sold.sum()),'lost_sales':float(lost.sum()),
                'on_hand':float(self.on_hand.sum()),'stockout_pairs':int((lost>0).sum()),'pairs':self.panel.n,
                'holding':float(np.sum(self.on_hand*costs*self.config.solver.holding_rate)),
                'shortage':float(np.sum(lost*costs*self.config.solver.shortage_multiplier)),
                'spoilage':float(np.sum(overflow*costs)), 'spoilage_units':float(overflow.sum()),
                'received_units':float(self.received.sum()),'received_order_ids':self.received_ids,
                'sales_by_series':sold.tolist(),'lost_by_series':lost.tolist(),'on_hand_by_series':self.on_hand.tolist()}
        self.previous_start=start
        return result
